"""Local AgentParty status reader.

The statusbar must not call AgentParty commands or hit the network. It only
reads the cwd-scoped cache written by the AgentParty CLI:
~/.agentparty/state/<workspaceId>/statusline.json.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Union


STALE_AFTER_SECONDS = 10 * 60

# Byte needles that mark a session as AgentParty-attached when they appear in
# its transcript. Command invocations and the config env var only — a session
# merely *talking about* AgentParty shouldn't light the line up. All are plain
# ASCII, so they survive JSONL string escaping verbatim.
_ATTACH_NEEDLES = (
    b"party init",
    b"party send",
    b"party watch",
    b"party serve",
    b"party ask",
    b"party digest",
    b"AGENTPARTY_CONFIG",
)

_CONFIG_QUOTED_RE = re.compile(
    rb"AGENTPARTY_CONFIG\s*=\s*\\?[\"'](.*?)\\?[\"']"
)
_CONFIG_UNQUOTED_RE = re.compile(
    rb"AGENTPARTY_CONFIG\s*=\s*([^\s\"'\\]+)"
)
_SCAN_OVERLAP = 4096


@dataclass(frozen=True)
class PartyStatus:
    channel: str = ""
    server: str = ""
    identity_name: str = ""
    identity_kind: str = "agent"
    identity_role: str = ""
    unread: int = 0
    last_from: str = ""
    last_preview: str = ""
    last_age: str = ""
    listener_mode: str = ""
    listener_pid: Optional[int] = None
    listener_alive: bool = False
    listener_stale: bool = False
    listener_present: bool = False
    listener_mentions_only: bool = False
    mentioned: bool = False
    fresh: bool = True


@dataclass(frozen=True)
class SessionPartyContext:
    attached: bool = False
    config_path: Optional[str] = None


def _coerce_path(path: Union[str, Path]) -> Path:
    # Match Node's path.resolve used by AgentParty: absolutize syntactically,
    # but do not realpath symlinks such as macOS /tmp -> /private/tmp.
    return Path(os.path.abspath(os.path.expanduser(str(path))))


def workspace_id(cwd: Union[str, Path]) -> str:
    path = _coerce_path(cwd)
    base = path.name or "workspace"
    slug = re.sub(r"[^a-z0-9._-]+", "-", base.lower())
    slug = re.sub(r"^[^a-z0-9]+|[^a-z0-9]+$", "", slug)
    slug = slug[:48] or "workspace"

    import hashlib
    digest = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:16]
    return f"{slug}-{digest}"


def agentparty_home() -> Path:
    raw = os.environ.get("AGENTPARTY_HOME")
    return Path(raw).expanduser() if raw else Path.home() / ".agentparty"


def state_dir_for(cwd: Union[str, Path], home: Optional[Path] = None) -> Path:
    root = home if home is not None else agentparty_home()
    return root / "state" / workspace_id(cwd)


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _int_or_none(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _pid_alive(pid: Optional[int]) -> bool:
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


_ARGV_CACHE: Dict[int, str] = {}


def _listener_argv(pid: Optional[int]) -> Optional[str]:
    """The process's command line, or None when it can't be read.

    An argv never changes for a given process, so the `ps` fork is memoised
    per pid (~4ms per fork — half a warm render). A transient failure is NOT
    cached, so it gets retried. (The memo is keyed by pid, so a recycled pid
    can serve a stale answer until the cache clears — which is why contract
    fields, when present, always win over argv probing.)
    """
    if pid is None or pid <= 0:
        return None
    cached = _ARGV_CACHE.get(pid)
    if cached is not None:
        return cached
    try:
        import subprocess
        proc = subprocess.run(
            ["ps", "-o", "command=", "-p", str(pid)],
            capture_output=True, text=True, timeout=0.6,
        )
        if proc.returncode != 0:
            return None
    except Exception:
        return None
    argv = (proc.stdout or "").strip()
    if not argv:
        return None
    # Bound the map — a long-lived daemon would otherwise accumulate dead pids.
    if len(_ARGV_CACHE) > 64:
        _ARGV_CACHE.clear()
    _ARGV_CACHE[pid] = argv
    return argv


def _argv_is_party(argv: str) -> bool:
    """True when the command line looks like an AgentParty listener."""
    return re.search(r"(^|/| )party($| )", argv) is not None


def _listener_mentions_only(pid: Optional[int]) -> bool:
    """Fallback for AgentParty CLIs older than 0.2.79 — see _listener_argv."""
    argv = _listener_argv(pid)
    return argv is not None and "--mentions-only" in argv


def _is_mentioned(preview: str, name: str) -> bool:
    """True when `preview` @-mentions `name`.

    The writer caps `preview` at 48 chars, so a mention past that cut is
    invisible here — this under-reports rather than over-reports.
    """
    if not preview or not name:
        return False
    return re.search(rf"@{re.escape(name)}(?![\w.-])", preview) is not None


def _format_age(ts_value: Any, now_seconds: float) -> str:
    try:
        ts = float(ts_value)
    except (TypeError, ValueError):
        return ""
    if ts <= 0:
        return ""
    if ts > 1_000_000_000_000:
        ts = ts / 1000.0
    delta = max(0, int(now_seconds - ts))
    if delta < 60:
        return f"{delta}s"
    if delta < 3600:
        return f"{delta // 60}m"
    if delta < 86400:
        return f"{delta // 3600}h"
    return f"{delta // 86400}d"


def _expand_config_path(value: str) -> str:
    """Expand shell path syntax without evaluating commands."""
    def _default(match: re.Match) -> str:
        return os.environ.get(match.group(1)) or match.group(2)

    value = re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*):-([^}]*)\}",
                   _default, value)
    return os.path.expandvars(os.path.expanduser(value.replace(r"\/", "/")))


def _tool_commands(chunk: bytes) -> list[str]:
    """Return shell commands from actual tool-use records in JSONL."""
    commands: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item)
            return
        if not isinstance(value, dict):
            return
        if value.get("type") == "tool_use":
            command = value.get("command")
            tool_input = value.get("input")
            if not isinstance(command, str) and isinstance(tool_input, dict):
                command = tool_input.get("command")
            name = value.get("name")
            shell_tool = not isinstance(name, str) or name.lower() in {
                "bash", "shell", "exec_command",
            }
            if isinstance(command, str) and shell_tool:
                commands.append(command)
        for child in value.values():
            visit(child)

    for line in chunk.splitlines():
        try:
            visit(json.loads(line))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    return commands


def _latest_config_path(
    commands: list[str],
    cwd: Optional[Union[str, Path]] = None,
) -> Optional[str]:
    for command in reversed(commands):
        encoded = command.encode("utf-8")
        matches = []
        for pattern in (_CONFIG_QUOTED_RE, _CONFIG_UNQUOTED_RE):
            matches.extend(pattern.finditer(encoded))
        for match in sorted(matches, key=lambda item: item.start(), reverse=True):
            candidate = Path(_expand_config_path(
                match.group(1).decode("utf-8")))
            if not candidate.is_absolute() and cwd is not None:
                candidate = _coerce_path(cwd) / candidate
            config = _read_json(candidate)
            identity = config.get("identity")
            if isinstance(identity, dict) and identity.get("name"):
                return str(candidate)
    return None


def session_party_context(
    transcript_path: str,
    session_id: str,
    *,
    cwd: Optional[Union[str, Path]] = None,
) -> SessionPartyContext:
    """Resolve AgentParty attachment and config for one editor session.

    The AgentParty state cache is cwd-scoped by contract, but Claude Code
    sessions are not: several sessions share one project directory, and only
    some of them join a party channel (typically via a per-session
    ``AGENTPARTY_CONFIG``). The env var never reaches the Claude Code process
    (agents export it inside individual Bash calls), so the only
    session-scoped evidence is the session's own transcript — a joined session
    necessarily ran ``party init/send/watch/…`` through the Bash tool.

    Scans are incremental and attachment is sticky. The latest explicit config
    path remains session-scoped, allowing two sessions in one cwd to retain
    distinct identities even though statusline.json is shared.
    """
    if not transcript_path or not session_id:
        return SessionPartyContext()
    try:
        tsize = os.path.getsize(transcript_path)
    except OSError:
        return SessionPartyContext()

    from .daemon import session_dir
    marker = session_dir(session_id) / "party_scan.json"
    state = _read_json(marker)
    was_attached = bool(state.get("attached"))
    cached_path = (state.get("config_path")
                   if isinstance(state.get("config_path"), str) else None)
    offset = state.get("offset")
    offset = offset if isinstance(offset, int) and 0 <= offset <= tsize else 0

    if offset == tsize and (cached_path or not was_attached):
        return SessionPartyContext(was_attached, cached_path)

    # Markers created before config-path tracking stopped at the first party
    # command. Re-scan once so an older session can recover its own identity.
    if was_attached and not cached_path:
        offset = 0

    start = max(0, offset - _SCAN_OVERLAP)
    try:
        with open(transcript_path, "rb") as f:
            f.seek(start)
            chunk = f.read()
    except OSError:
        return SessionPartyContext(was_attached, cached_path)
    commands = _tool_commands(chunk)
    command_bytes = [command.encode("utf-8") for command in commands]
    attached = was_attached or any(
        needle in command
        for command in command_bytes
        for needle in _ATTACH_NEEDLES
    )
    config_path = _latest_config_path(commands, cwd=cwd) or cached_path

    try:
        from .cache import atomic_write_text
        atomic_write_text(marker, json.dumps(
            {"attached": attached, "config_path": config_path,
             "offset": tsize}))
    except Exception:
        pass
    return SessionPartyContext(attached, config_path)


def session_is_attached(transcript_path: str, session_id: str) -> bool:
    """True when THIS session has ever run an AgentParty command."""
    return session_party_context(transcript_path, session_id).attached


def read_party_status(
    cwd: Union[str, Path],
    *,
    now: Optional[float] = None,
    home: Optional[Path] = None,
    config_path: Optional[Union[str, Path]] = None,
) -> Optional[PartyStatus]:
    """Return the local AgentParty status for cwd, or None when absent.

    `now` is seconds since epoch. Tests pass it explicitly; production uses
    time.time(). The AgentParty cache stores millisecond timestamps.
    """
    now_seconds = time.time() if now is None else now
    state_dir = state_dir_for(cwd, home=home)
    data = _read_json(state_dir / "statusline.json")
    if not data:
        return None

    updated_at = _int_or_none(data.get("updated_at"))
    fresh = True
    if updated_at:
        fresh = (now_seconds * 1000.0 - updated_at) <= STALE_AFTER_SECONDS * 1000

    identity = data.get("identity") if isinstance(data.get("identity"), dict) else {}
    if config_path:
        config_file = Path(config_path)
        if not config_file.is_absolute():
            config_file = _coerce_path(cwd) / config_file
        config = _read_json(config_file)
        session_identity = config.get("identity")
        if (isinstance(session_identity, dict)
                and session_identity.get("name")):
            identity = session_identity
    unread = _int_or_none(data.get("unread")) or 0
    last = data.get("last_message") if isinstance(data.get("last_message"), dict) else {}
    listener = data.get("listener") if isinstance(data.get("listener"), dict) else {}
    listener_pid = _int_or_none(listener.get("pid"))
    # The contract field is `heartbeat_ts`; `heartbeat_at` is tolerated for
    # older CLIs. Reading only the latter made every live listener look dead.
    listener_heartbeat = _int_or_none(listener.get("heartbeat_ts"))
    if listener_heartbeat is None:
        listener_heartbeat = _int_or_none(listener.get("heartbeat_at"))
    listener_alive = _pid_alive(listener_pid) if listener else False
    listener_fresh = False
    if listener_heartbeat:
        listener_fresh = (
            now_seconds * 1000.0 - listener_heartbeat
        ) <= STALE_AFTER_SECONDS * 1000

    # Heartbeats only tick with traffic on CLIs older than 0.2.80, so a quiet
    # channel left heartbeat_ts stale and a healthily connected listener
    # rendered as "down". The process itself is the better witness: alive AND
    # verifiably a party process → live, whatever the heartbeat age. If argv
    # can't be read (ps failure), fall back to the heartbeat. A recycled pid
    # reads as not-party → down, as it should.
    listener_live = False
    if listener and listener_alive:
        if listener_fresh:
            listener_live = True
        else:
            argv = _listener_argv(listener_pid)
            listener_live = (_argv_is_party(argv) if argv is not None
                             else False)

    listener_ok = listener_live
    preview = str(last.get("preview") or "")
    name = str(identity.get("name") or "")

    return PartyStatus(
        channel=str(data.get("channel") or ""),
        server=str(data.get("server") or ""),
        identity_name=name,
        identity_kind=str(identity.get("kind") or "agent"),
        identity_role=str(identity.get("role") or ""),
        unread=max(0, unread),
        last_from=str(last.get("from") or ""),
        last_preview=preview,
        last_age=_format_age(last.get("ts"), now_seconds),
        listener_mode=str(listener.get("mode") or "") if listener else "",
        listener_pid=listener_pid,
        listener_alive=listener_alive,
        listener_stale=bool(listener) and not listener_live,
        listener_present=bool(listener),
        # Contract field (agentparty >= 0.2.79) wins; fall back to probing the
        # listener's argv for older CLIs that don't write it.
        listener_mentions_only=(
            bool(listener.get("mentions_only"))
            if "mentions_only" in listener
            else (_listener_mentions_only(listener_pid) if listener_ok else False)
        ),
        mentioned=_is_mentioned(preview, name),
        fresh=fresh,
    )
