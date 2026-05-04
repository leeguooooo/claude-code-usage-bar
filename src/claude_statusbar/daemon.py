"""Long-lived render daemon (Phase B).

Why this exists
---------------
Claude Code re-invokes the statusLine command every `refreshInterval`
seconds. At `refreshInterval: 1` (one Hz), that's 60 Python interpreter
cold starts per minute — Phase A trimmed it to ~45ms each, but ~30ms is
unavoidable interpreter startup. This daemon eliminates that floor by
keeping a Python process alive: it pre-renders the status line into
``rendered.ansi`` on a tick, and the cheap ``cs render`` thin client just
reads + prints the file.

Lifecycle
---------
* Started by the user (``cs daemon start``) or lazily spawned by
  ``cs render`` when ``rendered.meta.json`` is stale.
* Holds an ``fcntl.flock`` on ``daemon.pid`` — only one daemon per user.
* Two cadences:
    - heavy tick (default 30s): re-runs claude-monitor / direct analysis,
      caches the result in-memory.
    - light tick (default 1s): re-renders ``rendered.ansi`` using the
      cached heavy data + freshly computed cache_age. Atomic write.
* Exits cleanly on SIGTERM / SIGINT — ``cs daemon stop`` sends SIGTERM.

Crash safety
------------
* All writes go through ``cache.atomic_write_text`` (sibling tempfile +
  ``os.replace``).
* The thin client's watchdog (``rendered.meta.json.generated_at`` > 5s
  stale) means a frozen / crashed daemon never freezes the user's status
  line — the thin client falls back to inline render on the next tick.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Optional

from .cache import atomic_write_text


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
def _cache_dir() -> Path:
    """All daemon state lives under one directory we own."""
    d = Path.home() / ".cache" / "claude-statusbar"
    d.mkdir(parents=True, exist_ok=True)
    return d


def pid_path() -> Path: return _cache_dir() / "daemon.pid"
def rendered_path() -> Path: return _cache_dir() / "rendered.ansi"
def meta_path() -> Path: return _cache_dir() / "rendered.meta.json"
def log_path() -> Path: return _cache_dir() / "daemon.log"


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
DEFAULT_HEAVY_INTERVAL = 30.0   # seconds
DEFAULT_RENDER_INTERVAL = 1.0   # seconds
META_STALE_AFTER = 5.0          # seconds — thin client treats older as dead

_running = True
_pidfile_handle = None  # type: Optional[object]


def _shutdown(_signum, _frame):
    global _running
    _running = False


# ---------------------------------------------------------------------------
# Pidfile + flock
# ---------------------------------------------------------------------------
def _acquire_pidfile() -> bool:
    """Take an exclusive flock on daemon.pid. Returns False if another
    daemon already holds it (or if flock isn't available on this platform)."""
    global _pidfile_handle
    try:
        import fcntl
    except ImportError:
        # Windows — skip locking. Single daemon per user honor system.
        _pidfile_handle = open(pid_path(), "w")
        _pidfile_handle.write(str(os.getpid()))
        _pidfile_handle.flush()
        return True

    fh = open(pid_path(), "a+")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.close()
        return False
    fh.seek(0)
    fh.truncate()
    fh.write(str(os.getpid()))
    fh.flush()
    _pidfile_handle = fh
    return True


def _release_pidfile():
    global _pidfile_handle
    if _pidfile_handle is None:
        return
    try:
        _pidfile_handle.close()
    except OSError:
        pass
    try:
        pid_path().unlink()
    except OSError:
        pass
    _pidfile_handle = None


def read_pidfile() -> Optional[int]:
    """Return the recorded daemon PID, or None if no daemon is registered."""
    p = pid_path()
    if not p.exists():
        return None
    try:
        return int(p.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def is_alive(pid: int) -> bool:
    """Best-effort liveness check — does this PID still exist?"""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


# ---------------------------------------------------------------------------
# Render — capture core.main()'s stdout into a string
# ---------------------------------------------------------------------------
def _render_once() -> Optional[str]:
    """Drive core.main() through redirect_stdout to grab the rendered ANSI.

    The daemon pretends to be Claude Code: it replays the cached stdin
    payload (last_stdin.json) into sys.stdin, calls core.main with side
    effects suppressed, and captures whatever is printed.
    """
    cache_file = _cache_dir() / "last_stdin.json"
    try:
        payload = cache_file.read_text(encoding="utf-8")
    except OSError:
        # No cached stdin yet — nothing to render. Daemon will retry next tick.
        return None

    buf = io.StringIO()
    saved_stdin = sys.stdin
    sys.stdin = io.StringIO(payload)
    try:
        with contextlib.redirect_stdout(buf):
            from .core import main as core_main
            core_main(_suppress_side_effects=True)
    except Exception as e:
        _log(f"render failed: {e!r}")
        return None
    finally:
        sys.stdin = saved_stdin

    out = buf.getvalue().rstrip("\n")
    return out or None


# ---------------------------------------------------------------------------
# Atomic publish
# ---------------------------------------------------------------------------
def _publish(rendered: str) -> None:
    """Write rendered.ansi + rendered.meta.json. Both atomic."""
    now = time.time()
    atomic_write_text(rendered_path(), rendered + "\n")
    meta = {
        "generated_at": now,
        "pid": os.getpid(),
        "stale_after_seconds": META_STALE_AFTER,
    }
    atomic_write_text(meta_path(), json.dumps(meta) + "\n")


# ---------------------------------------------------------------------------
# Logging — minimal, file only
# ---------------------------------------------------------------------------
def _log(msg: str) -> None:
    try:
        with open(log_path(), "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def run_forever(render_interval: float = DEFAULT_RENDER_INTERVAL) -> int:
    """Block in the render loop until SIGTERM/SIGINT.

    `core.main()` already throttles its heavy claude-monitor subprocess
    behind cache.py's age-based invalidation, so we don't need a separate
    "heavy tick" — every render tick that triggers a refresh hits the
    cache, only the periodic invalidation pays the heavy cost.
    """
    if not _acquire_pidfile():
        existing = read_pidfile()
        sys.stderr.write(
            f"daemon already running (pid {existing}); use `cs daemon stop` first\n"
        )
        return 1

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    _log(f"daemon started pid={os.getpid()} interval={render_interval}s")

    try:
        while _running:
            t0 = time.time()
            rendered = _render_once()
            if rendered is not None:
                _publish(rendered)
            elapsed = time.time() - t0
            sleep_for = max(0.0, render_interval - elapsed)
            # Sleep in small chunks so signals are responsive.
            end = time.time() + sleep_for
            while _running and time.time() < end:
                time.sleep(min(0.2, end - time.time()))
        _log("daemon shutting down")
        return 0
    finally:
        _release_pidfile()


# ---------------------------------------------------------------------------
# Subcommand handlers (called from cli.py)
# ---------------------------------------------------------------------------
def cmd_status() -> int:
    """`cs daemon status` — report whether daemon is alive and rendered.ansi
    freshness."""
    pid = read_pidfile()
    if pid is None:
        print("daemon: not running (no pidfile)")
        return 1
    alive = is_alive(pid)
    print(f"daemon: pid {pid} {'alive' if alive else 'STALE pidfile (process gone)'}")
    if not alive:
        return 1
    try:
        meta = json.loads(meta_path().read_text(encoding="utf-8"))
        age = time.time() - float(meta.get("generated_at", 0))
        print(f"rendered.ansi: {age:.1f}s old (stale_after={meta.get('stale_after_seconds')}s)")
        if age > META_STALE_AFTER:
            print("WARNING: rendered output is stale — daemon may be wedged")
            return 2
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(f"rendered.meta.json unreadable: {e}")
        return 2
    return 0


def cmd_stop() -> int:
    """`cs daemon stop` — SIGTERM the recorded pid."""
    pid = read_pidfile()
    if pid is None:
        print("daemon: not running")
        return 0
    if not is_alive(pid):
        print(f"daemon: pid {pid} already gone; cleaning pidfile")
        try:
            pid_path().unlink()
        except OSError:
            pass
        return 0
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as e:
        print(f"failed to signal pid {pid}: {e}", file=sys.stderr)
        return 1
    # Wait briefly for clean shutdown.
    for _ in range(20):
        time.sleep(0.1)
        if not is_alive(pid):
            print(f"daemon stopped (pid {pid})")
            return 0
    print(f"daemon (pid {pid}) did not exit within 2s; pidfile may be stale", file=sys.stderr)
    return 1


def cmd_start(detach: bool = True, render_interval: float = DEFAULT_RENDER_INTERVAL) -> int:
    """`cs daemon start` — fork a detached daemon, or run inline if --foreground."""
    pid = read_pidfile()
    if pid is not None and is_alive(pid):
        print(f"daemon: already running (pid {pid})")
        return 0
    if not detach:
        # Run in current process (used for testing + `--foreground`).
        return run_forever(render_interval=render_interval)
    # Spawn detached child via subprocess.Popen so the parent can return
    # immediately. Stdin/out/err to /dev/null; the child runs run_forever.
    import subprocess
    child = subprocess.Popen(
        [sys.executable, "-m", "claude_statusbar.cli", "daemon", "_run",
         "--render-interval", str(render_interval)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    # Give it a moment to acquire the pidfile.
    for _ in range(20):
        time.sleep(0.1)
        rec = read_pidfile()
        if rec and is_alive(rec):
            print(f"daemon started (pid {rec})")
            return 0
    print(f"daemon spawn appeared to fail; child pid was {child.pid}", file=sys.stderr)
    return 1


def spawn_if_dead(render_interval: float = DEFAULT_RENDER_INTERVAL) -> bool:
    """Best-effort lazy spawn for the thin client.

    Called when ``cs render`` notices ``rendered.meta.json`` is stale.
    Returns True if a daemon now exists (already alive or freshly spawned),
    False if spawn failed silently.
    """
    pid = read_pidfile()
    if pid is not None and is_alive(pid):
        return True
    try:
        import subprocess
        subprocess.Popen(
            [sys.executable, "-m", "claude_statusbar.cli", "daemon", "_run",
             "--render-interval", str(render_interval)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True
    except OSError:
        return False
