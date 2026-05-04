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


def _is_fresh(meta: dict) -> bool:
    """Daemon's last write must be within stale_after_seconds of now.

    Clock skew defense: if `generated_at` is in the future (NTP correction,
    container time-warp, user setting clock backward), treat the entry as
    STALE. Otherwise a wall-clock jump backward would freeze stale daemon
    output for the duration of the skew.
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
    return delta <= stale_after


# Legacy single-file path: still written for backward compat (old tooling
# / cs doctor / preview that look at top-level last_stdin.json), but the
# daemon reads from per-session paths now.
_LEGACY_STDIN_CACHE = _CACHE_DIR / "last_stdin.json"


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
    the payload is malformed or doesn't include one (e.g. very old Claude
    Code versions). Cost: one json.loads call (~0.05ms for typical payload)."""
    try:
        d = json.loads(payload.decode("utf-8", errors="replace"))
        sid = d.get("session_id") or "default"
        return str(sid)
    except (ValueError, json.JSONDecodeError):
        return "default"


def _atomic_write_bytes(target: Path, data: bytes) -> None:
    """Sibling tempfile + os.replace. Inlined so the fast path doesn't
    need to import cache.atomic_write_text."""
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".thin.tmp")
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
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
    """Run the legacy inline render path. Costs ~45ms (Phase A baseline)."""
    from .core import main as core_main
    core_main()
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
            sys.stdout.write(rendered_path.read_text(encoding="utf-8"))
            return 0
        except OSError:
            # rendered.ansi disappeared between the meta read and the read.
            # Fall through to inline.
            pass

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
