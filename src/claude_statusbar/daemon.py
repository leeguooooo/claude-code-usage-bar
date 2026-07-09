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
def log_path() -> Path: return _cache_dir() / "daemon.log"
# Windows-only lock sentinel — msvcrt byte locks are mandatory, so the lock
# lives on this file and daemon.pid stays readable by stop/status.
def lock_path() -> Path: return _cache_dir() / "daemon.lock"


# Per-session state (v3.3.0+) — multi-window safe.
# Each Claude Code window has a unique session_id; we render each one to its
# own bucket so two windows never overwrite each other's rendered.ansi.
def sessions_root() -> Path:
    d = _cache_dir() / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def session_dir(session_id: str) -> Path:
    """Per-session state directory. session_id comes from Claude Code's
    stdin payload — a UUID-like string, safe to use as a path segment
    after sanitisation."""
    safe = "".join(c for c in (session_id or "default") if c.isalnum() or c in "-_")[:64]
    if not safe:
        safe = "default"
    d = sessions_root() / safe
    d.mkdir(parents=True, exist_ok=True)
    return d


def session_stdin_path(session_id: str) -> Path:
    return session_dir(session_id) / "last_stdin.json"


def session_rendered_path(session_id: str) -> Path:
    return session_dir(session_id) / "rendered.ansi"


def session_meta_path(session_id: str) -> Path:
    return session_dir(session_id) / "rendered.meta.json"


SESSION_GC_AFTER_S = 24 * 60 * 60  # drop session dirs idle > 1 day
# Render only windows that are still ticking. Stopped Claude windows keep their
# session dirs for GC/debugging, but must not stay in the daemon's 1Hz work set.
ACTIVE_SESSION_AFTER_S = 10.0


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
    """Take an exclusive lock on daemon.pid. Returns False if another
    daemon already holds it.

    POSIX: fcntl.flock (unchanged). Windows: msvcrt.locking on a separate
    daemon.lock sentinel — the old "honor system" fallback always returned
    True, so every stale render tick leaked another daemon (issue #31,
    ~150 orphans/day).
    """
    global _pidfile_handle
    try:
        import fcntl
    except ImportError:
        return _acquire_pidfile_windows()

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


def _acquire_pidfile_windows(msvcrt_mod=None) -> bool:
    """Windows branch: exclusive msvcrt.locking on byte 0 of a SEPARATE
    sentinel file (daemon.lock), with the pid written to daemon.pid
    unlocked.

    The lock must NOT live on daemon.pid itself: msvcrt byte-range locks
    are MANDATORY (unlike POSIX flock) — while the daemon held it, every
    other process's read of daemon.pid raised a lock-violation OSError,
    so `cs daemon stop`/`status` saw "not running" and the CLI could
    never kill a live daemon.

    `msvcrt_mod` is injectable so the branch is unit-testable on POSIX CI
    (a fake module with `locking` / `LK_NBLCK` is enough). If msvcrt itself
    is missing (non-Windows caller without fcntl — exotic, but possible),
    fall back to the lock-free pid-liveness check instead of assuming we
    own the file.
    """
    global _pidfile_handle
    if msvcrt_mod is None:
        try:
            import msvcrt as msvcrt_mod
        except ImportError:
            return _acquire_pidfile_unlocked()

    fh = open(lock_path(), "a+")
    try:
        # Lock 1 byte at offset 0 — byte-range locks may extend past EOF
        # on Windows, so this works even on a freshly created empty file.
        fh.seek(0)
        msvcrt_mod.locking(fh.fileno(), msvcrt_mod.LK_NBLCK, 1)
    except OSError:
        # Held by another daemon (or the filesystem refused byte locks —
        # either way, don't risk a duplicate).
        fh.close()
        return False
    # Lock won — now record our pid in the (never-locked) pidfile so
    # stop/status/spawn_if_dead can read it while we run.
    try:
        pid_path().write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        try:
            msvcrt_mod.locking(fh.fileno(), msvcrt_mod.LK_UNLCK, 1)
        except OSError:
            pass
        fh.close()
        return False
    _pidfile_handle = fh
    return True


def _acquire_pidfile_unlocked() -> bool:
    """Belt-and-suspenders path when NO lock primitive exists: read the
    recorded pid and verify that process is alive before concluding no
    daemon runs. Weaker than a real lock (TOCTOU window between check and
    write), but combined with render_thin's spawn debounce it bounds the
    worst case to a short-lived duplicate rather than an unbounded leak.
    """
    global _pidfile_handle
    existing = read_pidfile()
    if existing is not None and existing != os.getpid() and is_alive(existing):
        return False
    fh = open(pid_path(), "w")
    fh.write(str(os.getpid()))
    fh.flush()
    _pidfile_handle = fh
    return True


def _release_pidfile():
    global _pidfile_handle
    if _pidfile_handle is None:
        return
    # Windows: explicitly drop the byte lock before close() — the OS can
    # lag releasing region locks on plain close, which would make the next
    # daemon's acquire fail spuriously. No-op on POSIX (ImportError) and
    # on the lock-free fallback path (OSError from LK_UNLCK).
    try:
        import msvcrt
        _pidfile_handle.seek(0)
        msvcrt.locking(_pidfile_handle.fileno(), msvcrt.LK_UNLCK, 1)
    except (ImportError, OSError, ValueError):
        pass
    try:
        _pidfile_handle.close()
    except OSError:
        pass
    for p in (pid_path(), lock_path()):
        try:
            p.unlink()
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
    """Best-effort liveness check — does this PID still exist?

    POSIX: kill(pid, 0), the classic no-op probe. Windows: os.kill(pid, 0)
    is NOT a probe there — CPython maps any non-CTRL sig to
    TerminateProcess, i.e. it would kill the daemon we're checking on —
    so use a ctypes OpenProcess query instead (stdlib-only, no psutil).
    """
    if pid <= 0:
        return False
    if os.name == "nt":
        return _is_alive_windows(pid)
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


# GetExitCodeProcess reports this magic value while the process still runs.
_STILL_ACTIVE = 259


def _is_alive_windows(pid: int, kernel32=None) -> bool:
    """Windows liveness via OpenProcess + GetExitCodeProcess.

    `kernel32` is injectable so this is unit-testable on POSIX CI. The
    exit-code check matters: OpenProcess can succeed on a terminated
    process whose handle someone still holds, and PIDs recycle — a bare
    handle check would over-report "alive".
    """
    import ctypes
    if kernel32 is None:
        try:
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        except AttributeError:
            return False
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid)
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return code.value == _STILL_ACTIVE
        # Handle opened but the query failed — assume alive (safer than
        # spawning a duplicate daemon).
        return True
    finally:
        kernel32.CloseHandle(handle)


def _process_is_our_daemon(pid: int) -> bool:
    """Verify the PID actually belongs to *our* daemon, not a recycled PID.

    Linux: read /proc/<pid>/cmdline directly (cheap, no fork).
    macOS / fallback: shell out to `ps -o command= -p <pid>` (~10ms — only
    runs on stop/install paths, never on the per-render hot path).

    Returns False on any error (better to assume not-ours and skip than to
    accidentally SIGTERM an unrelated user process).
    """
    proc_path = f"/proc/{pid}/cmdline"
    try:
        with open(proc_path, "rb") as f:
            cmdline = f.read().decode("utf-8", errors="replace")
        return "claude_statusbar" in cmdline and "daemon" in cmdline
    except OSError:
        pass
    # Non-Linux fallback.
    try:
        import subprocess
        out = subprocess.run(
            ["ps", "-o", "command=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        if out.returncode != 0:
            return False
        return "claude_statusbar" in out.stdout and "daemon" in out.stdout
    except (OSError, subprocess.TimeoutExpired):
        return False


# ---------------------------------------------------------------------------
# Render — capture core.main()'s stdout into a string
# ---------------------------------------------------------------------------
RENDER_TIMEOUT_S = 12  # cap per-session render so a slow JSONL scan can't
                       # starve other sessions. Larger than core's internal
                       # 10s subprocess timeout so the inner cap fires first.


class _RenderTimeout(Exception):
    """Raised by the SIGALRM handler when a single render exceeds RENDER_TIMEOUT_S."""


def _alarm_handler(_signum, _frame):
    raise _RenderTimeout()


def _render_payload(payload: str) -> Optional[str]:
    """Run core.main() with the given JSON payload as stdin and capture the
    rendered ANSI string. Used by the per-session render loop below.

    Hard timeout: signal.alarm caps each render at RENDER_TIMEOUT_S so one
    pathological session (e.g. multi-GB JSONL on slow NFS) can't starve the
    others. Daemon is POSIX-only; on Windows signal.alarm doesn't exist and
    we silently skip the timeout.

    Subprocess cleanup caveat: if SIGALRM fires while core_main() is blocked
    inside subprocess.run() (claude-monitor analysis), the inner subprocess
    becomes an orphan — Popen's __exit__/cleanup path is bypassed by the
    exception. The orphan re-parents to PID 1 and self-terminates within
    its own ~10s subprocess timeout. Acceptable: at most one orphan per
    timeout event, lifetime bounded.
    """
    buf = io.StringIO()
    saved_stdin = sys.stdin
    sys.stdin = io.StringIO(payload)

    have_alarm = hasattr(signal, "SIGALRM")
    old_handler = None
    if have_alarm:
        old_handler = signal.signal(signal.SIGALRM, _alarm_handler)
        signal.alarm(RENDER_TIMEOUT_S)

    try:
        with contextlib.redirect_stdout(buf):
            from .core import main as core_main
            core_main(_suppress_side_effects=True)
    except _RenderTimeout:
        _log(f"render timed out after {RENDER_TIMEOUT_S}s")
        return None
    except Exception as e:
        _log(f"render failed: {e!r}")
        return None
    finally:
        if have_alarm:
            signal.alarm(0)
            if old_handler is not None:
                signal.signal(signal.SIGALRM, old_handler)
        sys.stdin = saved_stdin

    out = buf.getvalue().rstrip("\n")
    return out or None


def _render_session(sid: str) -> bool:
    """Render one session's status line and atomically publish it.

    Returns True on success. False on any error (silent — daemon retries
    next tick; thin client falls back to inline if meta goes stale).
    """
    stdin_file = session_stdin_path(sid)
    try:
        payload = stdin_file.read_text(encoding="utf-8")
    except OSError:
        return False
    rendered = _render_payload(payload)
    if rendered is None:
        return False
    now = time.time()
    atomic_write_text(session_rendered_path(sid), rendered + "\n")
    atomic_write_text(session_meta_path(sid), json.dumps({
        "generated_at": now,
        "pid": os.getpid(),
        "stale_after_seconds": META_STALE_AFTER,
        "session_id": sid,
        # Thin client compares this against the package directory mtime
        # to detect "code on disk is newer than the running daemon".
        # See render_thin._is_fresh / _signal_outdated_daemon.
        "daemon_started_at": _DAEMON_STARTED_AT,
    }) + "\n")
    return True


def _active_sessions() -> list[str]:
    """List session_ids whose statusLine stdin was refreshed recently.

    This is intentionally much shorter than SESSION_GC_AFTER_S: GC decides when
    to delete old buckets, while this decides what the 1Hz daemon still renders.
    """
    out: list[tuple[float, str]] = []
    cutoff = time.time() - ACTIVE_SESSION_AFTER_S
    try:
        for d in sessions_root().iterdir():
            if not d.is_dir():
                continue
            stdin = d / "last_stdin.json"
            try:
                mtime = stdin.stat().st_mtime
                if mtime >= cutoff:
                    out.append((mtime, d.name))
            except OSError:
                continue
    except OSError:
        pass
    out.sort(reverse=True)
    return [sid for _, sid in out]


TMP_GC_AFTER_S = 60 * 60  # orphaned atomic-write temp files older than 1h


def _gc_orphan_tmp_files() -> None:
    """Remove orphaned ``.*.tmp`` files from the cache root.

    atomic_write_text writes to a sibling tempfile then os.replace()s it into
    place; a statusline process SIGKILLed between the two (Claude Code's 1s
    render timeout) leaks the tempfile. Observed live 2026-07-02: ~4900 leaked
    files. Anything older than TMP_GC_AFTER_S can't still be mid-write.
    """
    cutoff = time.time() - TMP_GC_AFTER_S
    try:
        for f in _cache_dir().iterdir():
            try:
                if (f.is_file() and f.name.startswith(".")
                        and f.name.endswith(".tmp")
                        and f.stat().st_mtime < cutoff):
                    f.unlink()
            except OSError:
                continue
    except OSError:
        pass


def _gc_old_sessions() -> None:
    """Drop session dirs that haven't been touched for SESSION_GC_AFTER_S.

    Called once per daemon-tick batch; cheap O(n) directory scan.
    """
    cutoff = time.time() - SESSION_GC_AFTER_S
    try:
        for d in sessions_root().iterdir():
            if not d.is_dir():
                continue
            try:
                stdin = d / "last_stdin.json"
                if stdin.exists() and stdin.stat().st_mtime >= cutoff:
                    continue
                # Stale — remove the whole directory.
                for f in d.iterdir():
                    try:
                        f.unlink()
                    except OSError:
                        pass
                d.rmdir()
                _log(f"gc'd stale session dir {d.name}")
            except OSError:
                continue
    except OSError:
        pass


def _render_all_sessions() -> int:
    """Render every active session. Returns the count rendered."""
    n = 0
    for sid in _active_sessions():
        if _render_session(sid):
            n += 1
    return n


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
_DAEMON_STARTED_AT: float = 0.0


def run_forever(render_interval: float = DEFAULT_RENDER_INTERVAL) -> int:
    """Block in the render loop until SIGTERM/SIGINT.

    `core.main()` already throttles its heavy claude-monitor subprocess
    behind cache.py's age-based invalidation, so we don't need a separate
    "heavy tick" — every render tick that triggers a refresh hits the
    cache, only the periodic invalidation pays the heavy cost.
    """
    # Reset module-level shutdown flag so an in-process restart (after a
    # previous SIGTERM call set _running=False) doesn't exit immediately.
    global _running, _DAEMON_STARTED_AT
    _running = True
    _DAEMON_STARTED_AT = time.time()

    if not _acquire_pidfile():
        existing = read_pidfile()
        sys.stderr.write(
            f"daemon already running (pid {existing}); use `cs daemon stop` first\n"
        )
        return 1

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    _log(f"daemon started pid={os.getpid()} interval={render_interval}s")

    GC_INTERVAL_S = 60 * 30  # garbage-collect stale session dirs every 30 min
    # Egress-IP risk re-check heartbeat. Runs on the daemon's own clock so a
    # network change (VPN on/off) reflects even while the user is idle and
    # Claude Code isn't re-rendering the statusline. The prober itself decides
    # whether a re-check is actually due (its own TTL) and self-throttles via
    # the inflight marker, so this can fire generously.
    IP_HEARTBEAT_S = 20.0
    # Defer the first *session* GC by one full interval — without this the
    # first tick of every fresh daemon would scan the sessions tree,
    # potentially racing with a Claude Code window that's mid-restart.
    last_gc = time.time()
    # Maintenance (orphan-tmp GC + update check) has no such race, so it runs
    # on the first tick. Deferring it starved both: this daemon is restarted
    # whenever the thin client spots code drift, and it rarely survives a full
    # GC_INTERVAL_S, so neither the tmp sweep nor the auto-update check ever
    # fired. Observed live: 15 orphaned .tmp files, the oldest 99 min old,
    # against a 60-minute TMP_GC_AFTER_S cutoff.
    last_maint = 0.0
    last_ip = 0.0
    try:
        while _running:
            t0 = time.time()
            _render_all_sessions()
            if t0 - last_ip > IP_HEARTBEAT_S:
                last_ip = t0
                # Only probe when the user actually enabled the egress-IP risk
                # line. Default users (show_ip_risk off) make ZERO third-party
                # calls — the feature is regional/niche and opt-in, so it must
                # never phone home for people who didn't ask for it.
                try:
                    from .config import load_config
                    if load_config().show_ip_risk:
                        from . import ip_risk
                        ip_risk.ensure_fresh()
                except Exception:
                    pass
            if t0 - last_maint > GC_INTERVAL_S:
                _gc_orphan_tmp_files()
                # The daemon is the long-lived process, so it owns the periodic
                # auto-update check (the per-render path suppresses side effects
                # in daemon mode). check_for_updates is 24h-throttled and only
                # SPAWNS a detached upgrade, so this never blocks the loop.
                try:
                    from .core import check_for_updates
                    check_for_updates()
                except Exception:
                    pass
                last_maint = t0
            if t0 - last_gc > GC_INTERVAL_S:
                _gc_old_sessions()
                last_gc = t0
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
    """`cs daemon status` — daemon liveness + per-session rendered freshness."""
    pid = read_pidfile()
    if pid is None:
        print("daemon: not running (no pidfile)")
        return 1
    alive = is_alive(pid)
    if alive and not _process_is_our_daemon(pid):
        print(f"daemon: pid {pid} alive but is not our daemon (PID was reused). Run `cs daemon stop` to clear stale pidfile.")
        return 1
    print(f"daemon: pid {pid} {'alive' if alive else 'STALE pidfile (process gone)'}")
    if not alive:
        return 1

    sids = _active_sessions()
    if not sids:
        print("sessions: none yet (daemon hasn't seen any cs render calls)")
        return 0
    print(f"sessions: {len(sids)} active")
    bad = 0
    for sid in sids:
        try:
            meta = json.loads(session_meta_path(sid).read_text(encoding="utf-8"))
            age = time.time() - float(meta.get("generated_at", 0))
            stale = age > META_STALE_AFTER
            tag = " STALE" if stale else ""
            print(f"  {sid[:8]}…  {age:.1f}s old{tag}")
            if stale:
                bad += 1
        except (OSError, ValueError, json.JSONDecodeError) as e:
            print(f"  {sid[:8]}…  meta unreadable: {e}")
            bad += 1
    return 0 if bad == 0 else 2


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
    # PID reuse defense: never SIGTERM a process we don't recognize as ours.
    if not _process_is_our_daemon(pid):
        print(
            f"daemon: pid {pid} is alive but is NOT our daemon (PID reused). "
            f"Refusing to SIGTERM. Manually remove {pid_path()} if you're sure.",
            file=sys.stderr,
        )
        return 1
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
    if pid is not None and is_alive(pid) and _process_is_our_daemon(pid):
        print(f"daemon: already running (pid {pid})")
        return 0
    # Stale pidfile (PID reused, or daemon SIGKILL'd without cleanup): drop
    # it so flock acquisition succeeds for the new daemon.
    if pid is not None:
        try:
            pid_path().unlink()
        except OSError:
            pass
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
    if pid is not None and is_alive(pid) and _process_is_our_daemon(pid):
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
