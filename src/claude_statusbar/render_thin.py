"""Thin status-line render client (Phase B).

Invoked by Claude Code on every statusline tick via ``cs render``. Goal:
do as little Python as possible — just read the daemon's pre-rendered
output and print it. If the daemon is dead or its output is stale, fall
back transparently to the inline render path so the user never sees a
frozen or empty status line.

The thin client also forwards Claude Code's stdin payload to
``~/.cache/claude-statusbar/last_stdin.json`` so the daemon sees fresh
``rate_limits`` / model / transcript_path on its next tick. Without this,
the daemon would keep re-rendering whatever snapshot was captured the
last time the inline path ran — token counters and 7d% would freeze.

Imports kept to bare stdlib (json, os, sys, time, pathlib) so the
import-time floor stays minimal. Heavier modules (core, styles, themes)
are deferred to the fallback path only.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# Same constants as daemon.py — keep in sync. Duplicated rather than
# imported so the happy path doesn't pull daemon.py in.
_CACHE_DIR = Path.home() / ".cache" / "claude-statusbar"
_SESSIONS_DIR = _CACHE_DIR / "sessions"
_STALE_AFTER_DEFAULT = 5.0  # seconds


def _sanitize_session_id(sid: str) -> str:
    """Same sanitisation as daemon.session_dir(). Duplicated to keep this
    module dependency-free."""
    safe = "".join(c for c in (sid or "default") if c.isalnum() or c in "-_")[:64]
    return safe or "default"


def _session_paths(sid: str) -> tuple[Path, Path, Path]:
    """Return (stdin, rendered, meta) for one session bucket."""
    d = _SESSIONS_DIR / _sanitize_session_id(sid)
    return d / "last_stdin.json", d / "rendered.ansi", d / "rendered.meta.json"


def _read_meta(meta_path: Path) -> dict | None:
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None


_PKG_DIR = Path(__file__).resolve().parent


def _pkg_mtime() -> float:
    """Newest mtime among files in the installed package directory.

    Used to detect "running daemon is older than the code on disk" (i.e.
    the user just upgraded via PyPI but the long-lived daemon is still
    serving stale renders). One `os.scandir` per render tick — cheap.
    Returns 0 on any I/O error so the freshness check degrades to its
    pre-upgrade behavior rather than thrashing.
    """
    try:
        return max(e.stat().st_mtime for e in os.scandir(_PKG_DIR)
                   if e.name.endswith(".py"))
    except OSError:
        return 0.0


def _is_fresh(meta: dict) -> bool:
    """Daemon's last write must be within stale_after_seconds of now AND
    the daemon must have started after the latest on-disk package code.

    Clock skew defense: if `generated_at` is in the future (NTP correction,
    container time-warp, user setting clock backward), treat the entry as
    STALE. Otherwise a wall-clock jump backward would freeze stale daemon
    output for the duration of the skew.

    Code-drift defense: if the package directory on disk has files newer
    than `daemon_started_at`, the daemon is running stale code (typical
    after a `pip install -U` while a long-lived daemon keeps serving).
    Treat as stale so the thin client falls back to inline + re-spawns
    a fresh daemon. Pre-3.8.1 daemons don't write `daemon_started_at`;
    those keep the old age-only behavior so upgrades roll out smoothly.
    """
    try:
        generated_at = float(meta.get("generated_at", 0))
        stale_after = float(meta.get("stale_after_seconds", _STALE_AFTER_DEFAULT))
    except (TypeError, ValueError):
        return False
    delta = time.time() - generated_at
    if delta < 0:
        # Future timestamp — treat as stale, fall back + re-spawn.
        return False
    if delta > stale_after:
        return False
    daemon_started_at = meta.get("daemon_started_at")
    if daemon_started_at is not None:
        try:
            started = float(daemon_started_at)
        except (TypeError, ValueError):
            return True  # malformed field; ignore code-drift check
        if _pkg_mtime() > started:
            return False
    return True


def _signal_outdated_daemon(meta: dict) -> None:
    """Send SIGTERM to the daemon pid recorded in `meta`. Used after
    `_is_fresh()` returns False due to code drift: the running daemon is
    serving stale renders and won't restart on its own (its pidfile is
    valid so lazy-spawn skips it). Best-effort — any error is silently
    swallowed; the worst case is a duplicate daemon for one render tick.
    """
    pid = meta.get("pid")
    if not isinstance(pid, int) or pid <= 1:
        return
    try:
        import signal as _signal
        os.kill(pid, _signal.SIGTERM)
    except (OSError, ProcessLookupError, PermissionError):
        pass


# Legacy single-file path: still written for backward compat (old tooling
# / cs doctor / preview that look at top-level last_stdin.json), but the
# daemon reads from per-session paths now.
_LEGACY_STDIN_CACHE = _CACHE_DIR / "last_stdin.json"

# Watched for displacement detection: if another tool (e.g. open-island)
# rewrites this file's statusLine.command, we still want to surface that
# in projects where a .claude/settings.json override keeps cs alive.
_USER_SETTINGS = Path.home() / ".claude" / "settings.json"
_OUR_BINARY_NAMES = ("cs", "cstatus", "claude-statusbar")


def _displacement_suffix() -> str:
    """If ~/.claude/settings.json statusLine points at a foreign binary,
    return a short ANSI-red suffix the caller can append to the bar.
    Empty string otherwise. Best-effort — never raises, never logs.

    One read_text() per render tick: skip the redundant exists() syscall
    and let FileNotFoundError (an OSError) signal "no file."
    """
    try:
        data = json.loads(_USER_SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # JSONDecodeError ⊂ ValueError
        return ""
    sl = data.get("statusLine") if isinstance(data, dict) else None
    if not isinstance(sl, dict):
        return ""
    cmd = sl.get("command")
    if not isinstance(cmd, str) or not cmd.strip():
        return ""
    name = Path(cmd.strip().split()[0]).name
    if name in _OUR_BINARY_NAMES:
        return ""
    # ANSI red. Kept short so it doesn't blow up the bar on narrow terminals.
    return f"  \x1b[31m⚠ statusLine 被 {name} 占用 · cs --setup\x1b[0m"


def _append_suffix(content: str, suffix: str) -> str:
    """Insert `suffix` before the trailing newline so it lands on the bar
    line, not the next line. No-op if suffix is empty."""
    if not suffix:
        return content
    if content.endswith("\n"):
        return content[:-1] + suffix + "\n"
    return content + suffix


def _consume_stdin() -> bytes | None:
    """Read Claude Code's stdin payload (bytes) and return it.

    Returns None if stdin is interactive or empty. Caller is responsible
    for both (a) writing it to per-session + legacy last_stdin.json so the
    daemon sees it on the next tick, and (b) replaying it into sys.stdin
    if the inline fallback path needs to consume it.
    """
    try:
        if sys.stdin.isatty():
            return None
    except (OSError, ValueError):
        return None
    try:
        data = sys.stdin.buffer.read()
    except (OSError, AttributeError):
        return None
    return data or None


def _extract_session_id(payload: bytes) -> str:
    """Pull session_id out of the JSON payload. Falls back to "default" if
    the payload is malformed, missing the field, or has a non-string value
    (e.g. null, 0, or a future Claude Code that nests it differently).

    Explicit type check prevents falsy-but-valid values like the integer 0
    from collapsing onto the "default" bucket via `or` short-circuit.
    Cost: one json.loads call (~0.05ms for typical payload).
    """
    try:
        d = json.loads(payload.decode("utf-8", errors="replace"))
    except (ValueError, json.JSONDecodeError):
        return "default"
    sid = d.get("session_id") if isinstance(d, dict) else None
    if not isinstance(sid, str) or not sid.strip():
        return "default"
    return sid


def _atomic_write_bytes(target: Path, data: bytes) -> None:
    """Sibling tempfile + os.replace. Inlined so the fast path doesn't
    need to import cache.atomic_write_text.

    No fsync: this writes the stdin snapshot at 1 Hz per window. Crash
    durability isn't worth the ~5-15ms penalty on slow / network FS —
    if we lose the snapshot, the very next tick writes a fresh one.
    The daemon's rendered.ansi write (in cache.atomic_write_text) keeps
    fsync because that file is consumed by potentially many readers.
    """
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".thin.tmp")
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
        os.replace(tmp, target)
    except OSError:
        pass


def _persist_stdin_bytes(data: bytes, session_id: str) -> None:
    """Write the stdin payload to BOTH the per-session bucket (so daemon
    renders this session) AND the legacy top-level file (for cs doctor /
    preview / inline fallback compatibility).

    Why per-session: multiple Claude Code windows used to overwrite each
    other's last_stdin.json, making the daemon flip-flop. Per-session
    paths keep them isolated.
    """
    session_stdin = _SESSIONS_DIR / _sanitize_session_id(session_id) / "last_stdin.json"
    _atomic_write_bytes(session_stdin, data)
    _atomic_write_bytes(_LEGACY_STDIN_CACHE, data)


def _spawn_daemon_async() -> None:
    """Best-effort spawn of cs daemon in a detached child process.

    Failures are silent — the user's status line already rendered via
    fallback, so we just want a daemon up for the *next* tick.
    """
    try:
        # Lazy import — only the fallback path pays for daemon.py.
        from .daemon import spawn_if_dead
        spawn_if_dead()
    except Exception:
        pass


def _fallback_inline() -> int:
    """Run the legacy inline render path. Costs ~45ms (Phase A baseline).

    Captures stdout so we can splice the displacement suffix onto the bar
    line — same warning the fast path appends. If suffix is empty we hand
    the captured output through unchanged.
    """
    import contextlib
    import io as _io
    from .core import main as core_main

    buf = _io.StringIO()
    with contextlib.redirect_stdout(buf):
        core_main()
    sys.stdout.write(_append_suffix(buf.getvalue(), _displacement_suffix()))
    return 0


def render() -> int:
    """Main entry point for ``cs render``.

    Returns the exit code; mirrors how the legacy `cs` invocation behaved.

    Multi-session safe (v3.3.0+): each Claude Code window's session_id
    routes to its own bucket in ~/.cache/claude-statusbar/sessions/<sid>/.
    Two windows side by side never overwrite each other's rendered.ansi.
    """
    # Capture Claude Code's stdin payload, route to per-session bucket.
    payload = _consume_stdin()
    session_id = "default"
    if payload is not None:
        session_id = _extract_session_id(payload)
        _persist_stdin_bytes(payload, session_id)

    # Fast path: if THIS session's daemon-rendered output is fresh, cat
    # the file and return. No core/styles/themes import.
    _, rendered_path, meta_path = _session_paths(session_id)
    meta = _read_meta(meta_path)
    if meta is not None and _is_fresh(meta):
        try:
            content = rendered_path.read_text(encoding="utf-8")
            sys.stdout.write(_append_suffix(content, _displacement_suffix()))
            return 0
        except OSError:
            # rendered.ansi disappeared between the meta read and the read.
            # Fall through to inline.
            pass

    # If the meta is stale because the daemon is running outdated code
    # (PyPI upgrade while daemon kept running), nudge it to exit so the
    # spawn below can bring up a fresh process. Old daemon's pidfile is
    # still valid otherwise and `_spawn_daemon_async` would refuse.
    if meta is not None:
        _signal_outdated_daemon(meta)

    # Fallback: render inline AND kick off a daemon spawn so the next
    # tick is fast. We don't wait for the daemon to come up — the user's
    # status line shows the inline-rendered string this tick.
    _spawn_daemon_async()
    if payload is not None:
        # core.main() reads sys.stdin via parse_stdin_data(); replay the
        # bytes we already consumed so it sees the same payload Claude Code
        # sent us.
        import io
        sys.stdin = io.StringIO(payload.decode("utf-8", errors="replace"))
    return _fallback_inline()
