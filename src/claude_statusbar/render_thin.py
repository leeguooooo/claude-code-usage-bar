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
_RENDERED = _CACHE_DIR / "rendered.ansi"
_META = _CACHE_DIR / "rendered.meta.json"
_STALE_AFTER_DEFAULT = 5.0  # seconds


def _read_meta() -> dict | None:
    try:
        return json.loads(_META.read_text(encoding="utf-8"))
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


_LAST_STDIN_CACHE = _CACHE_DIR / "last_stdin.json"


def _consume_stdin() -> bytes | None:
    """Read Claude Code's stdin payload (bytes) and return it.

    Returns None if stdin is interactive or empty. Caller is responsible
    for both (a) writing it to last_stdin.json so the daemon sees it on
    the next tick, and (b) replaying it into sys.stdin if the inline
    fallback path needs to consume it.
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


def _persist_stdin_bytes(data: bytes) -> None:
    """Atomic write of raw bytes to last_stdin.json. No JSON parse — the
    daemon validates on its next tick. ~1ms cost, never fatal.

    Why we MUST do this: Claude Code injects the *current* model +
    rate_limits + transcript path on every statusline invocation. The
    daemon re-reads last_stdin.json to pick up changes. Without this
    forwarding step, the daemon would be permanently stuck on whatever
    snapshot was captured the last time `core.main()` ran — token
    counters and 7d% would freeze the moment fast-mode was enabled.
    """
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        # Atomic: sibling tempfile + rename. Same pattern as
        # cache.atomic_write_text but inlined to avoid pulling cache.py
        # (and its imports) on the fast path.
        tmp = _LAST_STDIN_CACHE.with_suffix(".json.thin.tmp")
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, _LAST_STDIN_CACHE)
    except OSError:
        pass


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
    """
    # Capture Claude Code's stdin payload first. Both paths need it:
    #   - fast path: write to last_stdin.json so daemon's next tick is fresh
    #   - fallback: same write + replay into sys.stdin for core.main()
    payload = _consume_stdin()
    if payload is not None:
        _persist_stdin_bytes(payload)

    # Fast path: if daemon's output is fresh, cat the file and return.
    # No core/styles/themes import.
    meta = _read_meta()
    if meta is not None and _is_fresh(meta):
        try:
            sys.stdout.write(_RENDERED.read_text(encoding="utf-8"))
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
