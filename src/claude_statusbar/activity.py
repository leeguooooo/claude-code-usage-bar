"""Live-session activity, parsed from the Claude Code transcript JSONL.

Surfaces the "what is Claude doing right now" signals that the quota/cache
line can't show: todo progress, the currently-running tool, dispatched
subagents, plus cheap session stats (duration, lines changed) that Claude
Code already hands us on stdin.

Design constraints (this runs on the render hot path, once per refresh):
  * pure stdlib, no subprocess / no heavy imports (see test_import_perf)
  * the transcript scan is a bounded reverse-tail read (same 320KB budget as
    core._last_assistant_info) — never a full forward pass over a multi-MB
    file.

The reverse-tail direction is exactly right for "current" state: the newest
TodoWrite, the running tool, and the active agent all sit at the file tail,
and tool_result blocks (which mark a tool as finished) appear *after* their
tool_use, so scanning newest-first we meet the result before the use.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# Reuse the same byte budget as the cache-age reader so a giant transcript
# can't blow up render time.
_CHUNK = 32 * 1024
_MAX_BYTES = 10 * _CHUNK
# Cap completed-tool counting so "✓ Read ×N" reflects recent activity, not a
# lifetime total on a long session.
_RECENT_TOOLS_CAP = 25
_MAX_AGENTS = 3
# Conservative fallback TTL when the transcript carries no cache-write signal
# (caching disabled / pre-breakdown transcript). Matches Anthropic's base 5min.
_FALLBACK_TTL_S = 300

_MCP_RE = re.compile(r"^mcp__.+__.+$")
_TASK_ID_RE = re.compile(r"<task-id>([^<]+)</task-id>")
_TOOL_USE_ID_RE = re.compile(r"<tool-use-id>([^<]+)</tool-use-id>")

# Tools whose meaningful argument is a filesystem path → show the basename.
_FILE_TOOLS = {"Read", "Write", "Edit", "MultiEdit", "NotebookEdit"}
_PATTERN_TOOLS = {"Glob", "Grep"}
_AGENT_TOOLS = {"Task", "Agent"}

_BASH_MAX = 30


# ---------------------------------------------------------------------------
# Pure formatting helpers
# ---------------------------------------------------------------------------
def extract_target(name: str, inp: Dict[str, Any]) -> str:
    """The meaningful argument to show beside a tool name.

    Read/Write/Edit → file basename; Glob/Grep → pattern; Bash → the command
    truncated; Skill → the skill name. Unknown tools / missing args → "".
    """
    if not isinstance(inp, dict):
        return ""
    if name in _FILE_TOOLS:
        path = inp.get("file_path") or inp.get("path") or ""
        if not isinstance(path, str):  # malformed transcript — don't crash
            return ""
        return os.path.basename(path.rstrip("/")) if path else ""
    if name in _PATTERN_TOOLS:
        return str(inp.get("pattern") or "")
    if name == "Bash":
        cmd = str(inp.get("command") or "").strip()
        if len(cmd) > _BASH_MAX:
            return cmd[:_BASH_MAX] + "…"
        return cmd
    if name == "Skill":
        return str(inp.get("skill") or "")
    return ""


def shorten_tool_name(name: str, max_len: int = 20) -> str:
    """`mcp__figma__get_screenshot` → `get_screenshot`, then ellipsis-truncate."""
    if _MCP_RE.match(name or ""):
        name = name.split("__")[-1]
    if len(name) > max_len:
        return name[: max_len - 1] + "…"
    return name


def format_duration_short(ms: int) -> str:
    """Coarse session duration: `45s`, `12m`, `1h05m`. 0 → ""."""
    try:
        s = int(ms) // 1000
    except (TypeError, ValueError):
        return ""
    if s <= 0:
        return ""
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    return f"{s // 3600}h{(s % 3600) // 60:02d}m"


def format_lines(added: int, removed: int) -> str:
    """Session line delta: `+182 -47`, `+5`, `-3`. Both 0 → ""."""
    try:
        a, r = int(added), int(removed)
    except (TypeError, ValueError):
        return ""
    parts = []
    if a > 0:
        parts.append(f"+{a}")
    if r > 0:
        parts.append(f"-{r}")
    return " ".join(parts)


def format_elapsed_short(seconds: float) -> str:
    """Live elapsed for a running agent/tool: `<1s`, `45s`, `2m15s`, `1h05m`."""
    try:
        s = float(seconds)
    except (TypeError, ValueError):
        return ""
    if s < 1:
        return "<1s"
    s = int(s)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m{s % 60:02d}s"
    return f"{s // 3600}h{(s % 3600) // 60:02d}m"


def format_cache_countdown(age_seconds: Optional[float],
                           detected_ttl: Optional[int],
                           ttl_override: Optional[int] = None) -> str:
    """Format the prompt-cache countdown from a turn age + its detected TTL.

    Shared by ``core.get_cache_age_text`` and the merged single-scan render
    path so both produce byte-identical output:
      - "COLD" when there's no assistant turn (age None) or the cache expired.
      - "XhMMmSSs" / "MmSSs" / "Ys" remaining otherwise. Seconds are always
        shown (so the bar visibly ticks); sub-minute omits 'm' (the styles
        layer keys yellow off the missing 'm').
    """
    if age_seconds is None:
        return "COLD"
    ttl = ttl_override if ttl_override is not None else (
        detected_ttl if detected_ttl is not None else _FALLBACK_TTL_S)
    age = 0.0 if age_seconds < 0 else age_seconds  # clamp future timestamps
    remaining = ttl - age
    if remaining <= 0:
        return "COLD"
    remaining_int = int(remaining) if remaining == int(remaining) else int(remaining) + 1
    secs = remaining_int % 60
    if remaining_int >= 3600:
        return f"{remaining_int // 3600}h{(remaining_int % 3600) // 60:02d}m{secs:02d}s"
    mins = remaining_int // 60
    if mins > 0:
        return f"{mins}m{secs:02d}s"
    return f"{secs}s"


# ---------------------------------------------------------------------------
# Transcript scan
# ---------------------------------------------------------------------------
@dataclass
class ActivityInfo:
    """A snapshot of live session activity, all fields optional/empty."""

    todos: List[Tuple[str, str]] = field(default_factory=list)
    # (display_name, target) of the tool with no result yet, or None.
    active_tool: Optional[Tuple[str, str]] = None
    # [(display_name, count)] of recently-completed tools, most frequent first.
    completed_counts: List[Tuple[str, int]] = field(default_factory=list)
    # running subagents: [{name, model, description, elapsed_seconds, background}]
    agents: List[Dict[str, Any]] = field(default_factory=list)
    # prompt-cache countdown inputs, gathered in the same scan (see
    # format_cache_countdown): age of the newest assistant turn + the TTL it
    # applied. None when the transcript carries no assistant turn / no signal.
    cache_age_seconds: Optional[float] = None
    cache_ttl: Optional[int] = None

    @property
    def todos_total(self) -> int:
        return len(self.todos)

    @property
    def todos_done(self) -> int:
        return sum(1 for _, s in self.todos if s == "completed")

    @property
    def in_progress_todo(self) -> Optional[str]:
        for content, status in self.todos:
            if status == "in_progress":
                return content
        return None

    def is_empty(self) -> bool:
        return not (self.todos or self.active_tool
                    or self.completed_counts or self.agents)


def _parse_ts(ts_str: str) -> Optional[datetime]:
    """Parse a transcript ISO timestamp to an aware UTC datetime, or None."""
    if not isinstance(ts_str, str) or not ts_str:
        return None
    if ts_str.endswith("Z"):
        ts_str = ts_str[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(ts_str)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _entry_cache_ttl(entry: Dict[str, Any]) -> Optional[int]:
    """The prompt-cache TTL Anthropic applied on this turn (3600/300), or None.

    Read from `message.usage.cache_creation`: a nonzero `ephemeral_1h_input_tokens`
    means a 1-hour `cache_control` ttl, `ephemeral_5m_input_tokens` means 5min.
    """
    msg = entry.get("message")
    if not isinstance(msg, dict):
        return None
    usage = msg.get("usage")
    if not isinstance(usage, dict):
        return None
    cc = usage.get("cache_creation")
    if not isinstance(cc, dict):
        return None
    if (cc.get("ephemeral_1h_input_tokens") or 0) > 0:
        return 3600
    if (cc.get("ephemeral_5m_input_tokens") or 0) > 0:
        return 300
    return None


def _content_blocks(entry: Dict[str, Any]) -> List[Any]:
    msg = entry.get("message")
    if isinstance(msg, dict):
        c = msg.get("content")
        if isinstance(c, list):
            return c
    return []


def _iter_entries_reverse(transcript_path: str):
    """Yield parsed JSONL entries newest-first, bounded to _MAX_BYTES of tail.

    Mirrors core._last_assistant_info's chunked reverse read so a multi-MB
    transcript never costs more than the byte budget per render.
    """
    try:
        with open(transcript_path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            if size == 0:
                return
            buf = b""
            pos = size
            scanned = 0
            while pos > 0 and scanned < _MAX_BYTES:
                read = min(_CHUNK, pos)
                pos -= read
                scanned += read
                f.seek(pos)
                buf = f.read(read) + buf
                lines = buf.split(b"\n")
                if pos > 0:
                    buf = lines[0]
                    candidates = lines[1:]
                else:
                    buf = b""
                    candidates = lines
                for raw in reversed(candidates):
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        yield json.loads(raw)
                    except (ValueError, json.JSONDecodeError):
                        continue
    except OSError:
        return


def read_activity(transcript_path: str,
                  now: Optional[datetime] = None) -> ActivityInfo:
    """Scan the transcript tail (newest-first) for live activity.

    Extracts, in one bounded reverse-tail pass:
      * todos      — the newest TodoWrite list (last-write-wins: TodoWrite
                     carries the full list, so the first one we meet scanning
                     backward is the current state).
      * active_tool — the newest tool_use with no tool_result yet. Results
                     (in `user` entries) appear after their use in file order,
                     so scanning newest-first we meet the result before the
                     use; a use we reach without a recorded result is running.
      * completed_counts — frequency rollup of recently-finished tools.
      * agents     — running subagents (Task/Agent) with live elapsed time.
                     Inline agents finish via their tool_result; background
                     ones (run_in_background) finish via a queue-operation
                     `enqueue` whose content carries their <tool-use-id>.
    """
    now = now or datetime.now(timezone.utc)
    info = ActivityInfo()
    todos_found = False
    seen_results = set()        # tool_use_ids that already have a result
    enqueued = set()            # tool_use_ids surfaced by a queue-op enqueue
    completed: Dict[str, int] = {}
    completed_total = 0
    for entry in _iter_entries_reverse(transcript_path):
        if entry.get("type") == "queue-operation" and entry.get("operation") == "enqueue":
            for m in _TOOL_USE_ID_RE.finditer(str(entry.get("content") or "")):
                enqueued.add(m.group(1))
            continue
        # Cache countdown (same scan): newest assistant turn's age + the TTL
        # the newest cache-writing turn applied. Decoupled like core's reader.
        if entry.get("type") == "assistant":
            if info.cache_age_seconds is None:
                ts = _parse_ts(entry.get("timestamp", ""))
                if ts is not None:
                    info.cache_age_seconds = (now - ts).total_seconds()
            if info.cache_ttl is None:
                t = _entry_cache_ttl(entry)
                if t is not None:
                    info.cache_ttl = t
        for b in _content_blocks(entry):
            if not isinstance(b, dict):
                continue
            bt = b.get("type")
            if bt == "tool_result":
                tid = b.get("tool_use_id")
                if tid:
                    seen_results.add(tid)
                continue
            if bt != "tool_use":
                continue
            name = b.get("name") or ""
            # A malformed/corrupt transcript can carry a non-dict input that
            # still parses as valid JSON — normalize so no branch below
            # dereferences a str/list/int (which would crash the whole render).
            inp = b.get("input")
            if not isinstance(inp, dict):
                inp = {}
            if name == "TodoWrite":
                if not todos_found:
                    todos = inp.get("todos")
                    if isinstance(todos, list):
                        info.todos = [
                            (str(t.get("content", "")), str(t.get("status", "")))
                            for t in todos if isinstance(t, dict)
                        ]
                        todos_found = True
                continue
            if name in _AGENT_TOOLS:
                tid = b.get("id")
                background = bool(inp.get("run_in_background"))
                # A background dispatch returns an IMMEDIATE launch-ack
                # tool_result, so seen_results does NOT mean "done" for it —
                # only the later queue-op task-notification (enqueued) does.
                # Inline agents finish via their tool_result.
                done = (tid in enqueued) if background else (tid in seen_results)
                if done or len(info.agents) >= _MAX_AGENTS:
                    continue
                start = _parse_ts(entry.get("timestamp", ""))
                elapsed = max(0.0, (now - start).total_seconds()) if start else 0.0
                info.agents.append({
                    "name": str(inp.get("subagent_type") or "agent"),
                    "description": str(inp.get("description") or ""),
                    "model": str(inp.get("model") or ""),
                    "elapsed_seconds": elapsed,
                    "background": background,
                })
                continue
            if name in ("TaskCreate", "TaskUpdate"):
                continue
            display = shorten_tool_name(name)
            if b.get("id") in seen_results:
                if completed_total < _RECENT_TOOLS_CAP:
                    completed[display] = completed.get(display, 0) + 1
                    completed_total += 1
            elif info.active_tool is None:
                info.active_tool = (display, extract_target(name, inp))
    # Most frequent first; dict order (recency, newest-first) breaks ties.
    info.completed_counts = sorted(completed.items(), key=lambda kv: -kv[1])
    return info
