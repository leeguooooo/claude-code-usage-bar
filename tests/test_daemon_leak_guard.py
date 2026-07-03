"""Regression tests for issue #31 — Windows daemon process leak.

The old Windows branch of daemon._acquire_pidfile() was an "honor system"
that always returned True (fcntl missing → no lock at all), so every stale
render tick spawned another daemon. Three defenses now exist, each tested
here without needing a real Windows box:

1. msvcrt.locking-based exclusive lock (fake msvcrt module injected)
2. pid-liveness fallback when no lock primitive exists (incl. the ctypes
   OpenProcess probe — os.kill(pid, 0) on Windows TERMINATES the target)
3. render_thin spawn debounce (marker-file mtime, one attempt per 30s)
"""

import ctypes
import os
import sys
import time
from pathlib import Path

import pytest

from claude_statusbar import daemon as _d
from claude_statusbar import render_thin


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class FakeMsvcrt:
    """Just enough of msvcrt for _acquire_pidfile_windows."""
    LK_NBLCK = 2
    LK_UNLCK = 0

    def __init__(self, already_locked: bool = False):
        self.already_locked = already_locked
        self.calls = []

    def locking(self, fd, mode, nbytes):
        self.calls.append((mode, nbytes))
        if mode == self.LK_NBLCK and self.already_locked:
            # What real msvcrt.locking raises when another process holds it.
            raise OSError(36, "Resource deadlock avoided")


class FakeKernel32:
    """Just enough of ctypes.windll.kernel32 for _is_alive_windows."""
    def __init__(self, handle=1234, exit_code=_d._STILL_ACTIVE, query_ok=True):
        self.handle = handle
        self.exit_code = exit_code
        self.query_ok = query_ok
        self.closed = []

    def OpenProcess(self, access, inherit, pid):
        return self.handle

    def GetExitCodeProcess(self, handle, code_ref):
        if not self.query_ok:
            return 0
        code_ref._obj.value = self.exit_code  # write through ctypes.byref
        return 1

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return 1


def _isolate_pidfile(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(_d, "_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(_d, "_pidfile_handle", None)


# ---------------------------------------------------------------------------
# 1. Windows lock branch (fake msvcrt)
# ---------------------------------------------------------------------------
def test_windows_acquire_takes_lock_and_writes_pid(monkeypatch, tmp_path: Path):
    _isolate_pidfile(monkeypatch, tmp_path)
    fake = FakeMsvcrt()
    assert _d._acquire_pidfile_windows(fake) is True
    assert _d.read_pidfile() == os.getpid()
    assert (FakeMsvcrt.LK_NBLCK, 1) in fake.calls
    # REGRESSION GUARD: msvcrt byte locks are MANDATORY — if the lock sat
    # on daemon.pid itself, every other process's read_pidfile() would
    # raise a lock violation on real Windows, blinding stop/status. The
    # lock must live on the daemon.lock sentinel, pidfile stays unlocked.
    assert Path(_d._pidfile_handle.name).name == "daemon.lock"
    assert (tmp_path / "daemon.pid").read_text(encoding="utf-8") == str(os.getpid())
    _d._release_pidfile()
    # Release cleans up both the pidfile and the sentinel.
    assert not (tmp_path / "daemon.pid").exists()
    assert not (tmp_path / "daemon.lock").exists()


def test_windows_acquire_refuses_when_already_locked(monkeypatch, tmp_path: Path):
    _isolate_pidfile(monkeypatch, tmp_path)
    (tmp_path / "daemon.pid").write_text("4242", encoding="utf-8")
    fake = FakeMsvcrt(already_locked=True)
    assert _d._acquire_pidfile_windows(fake) is False
    # Loser must not clobber the holder's recorded pid, and must not
    # believe it owns the pidfile. (True on real Windows too, because the
    # loser fails on daemon.lock before ever touching daemon.pid.)
    assert _d.read_pidfile() == 4242
    assert _d._pidfile_handle is None


def test_windows_two_daemons_second_loses(monkeypatch, tmp_path: Path):
    """The exact issue-#31 scenario: two acquisitions, only one may win."""
    _isolate_pidfile(monkeypatch, tmp_path)
    assert _d._acquire_pidfile_windows(FakeMsvcrt()) is True
    winner_pid = _d.read_pidfile()
    # Second daemon: the winner's byte lock is still held.
    handle = _d._pidfile_handle
    monkeypatch.setattr(_d, "_pidfile_handle", None)
    assert _d._acquire_pidfile_windows(FakeMsvcrt(already_locked=True)) is False
    assert _d.read_pidfile() == winner_pid
    handle.close()


@pytest.mark.skipif(sys.platform == "win32", reason="needs a platform without msvcrt")
def test_windows_acquire_falls_back_to_liveness_without_msvcrt(monkeypatch, tmp_path: Path):
    """No msvcrt importable (this POSIX box) → belt-and-suspenders path."""
    _isolate_pidfile(monkeypatch, tmp_path)
    called = []
    monkeypatch.setattr(_d, "_acquire_pidfile_unlocked",
                        lambda: called.append(1) or False)
    assert _d._acquire_pidfile_windows() is False
    assert called == [1]


# ---------------------------------------------------------------------------
# 2. Lock-free liveness fallback
# ---------------------------------------------------------------------------
def test_unlocked_refuses_when_recorded_pid_alive(monkeypatch, tmp_path: Path):
    _isolate_pidfile(monkeypatch, tmp_path)
    (tmp_path / "daemon.pid").write_text("4242", encoding="utf-8")
    monkeypatch.setattr(_d, "is_alive", lambda pid: True)
    assert _d._acquire_pidfile_unlocked() is False
    assert _d._pidfile_handle is None


def test_unlocked_acquires_over_dead_pid(monkeypatch, tmp_path: Path):
    _isolate_pidfile(monkeypatch, tmp_path)
    (tmp_path / "daemon.pid").write_text("4242", encoding="utf-8")
    monkeypatch.setattr(_d, "is_alive", lambda pid: False)
    assert _d._acquire_pidfile_unlocked() is True
    assert _d.read_pidfile() == os.getpid()
    _d._release_pidfile()


def test_unlocked_acquires_when_no_pidfile(monkeypatch, tmp_path: Path):
    _isolate_pidfile(monkeypatch, tmp_path)
    assert _d._acquire_pidfile_unlocked() is True
    assert _d.read_pidfile() == os.getpid()
    _d._release_pidfile()


# ---------------------------------------------------------------------------
# Windows liveness probe (fake kernel32)
# ---------------------------------------------------------------------------
def test_is_alive_windows_running_process():
    k32 = FakeKernel32(exit_code=_d._STILL_ACTIVE)
    assert _d._is_alive_windows(4242, kernel32=k32) is True
    assert k32.closed == [1234]  # handle never leaked


def test_is_alive_windows_no_such_process():
    k32 = FakeKernel32(handle=0)
    assert _d._is_alive_windows(4242, kernel32=k32) is False
    assert k32.closed == []  # nothing to close


def test_is_alive_windows_exited_process():
    # OpenProcess can still succeed on a zombie whose handle someone holds;
    # the exit code disambiguates.
    k32 = FakeKernel32(exit_code=0)
    assert _d._is_alive_windows(4242, kernel32=k32) is False
    assert k32.closed == [1234]


def test_is_alive_windows_query_failure_assumes_alive():
    k32 = FakeKernel32(query_ok=False)
    assert _d._is_alive_windows(4242, kernel32=k32) is True
    assert k32.closed == [1234]


def test_is_alive_dispatches_to_windows_probe_on_nt(monkeypatch):
    # os.kill must NEVER run on nt — sig 0 maps to TerminateProcess there,
    # i.e. the "liveness check" would kill the daemon it's checking on.
    monkeypatch.setattr(_d.os, "name", "nt")
    monkeypatch.setattr(_d.os, "kill",
                        lambda *a: pytest.fail("os.kill called on nt"))
    monkeypatch.setattr(_d, "_is_alive_windows", lambda pid: True)
    assert _d.is_alive(4242) is True


def test_is_alive_rejects_nonpositive_pid():
    # Garbage pidfiles can decode to 0 / negatives; kill(0, 0) would probe
    # our own process group and always "succeed".
    assert _d.is_alive(0) is False
    assert _d.is_alive(-1) is False


# ---------------------------------------------------------------------------
# 3. Thin-client spawn debounce
# ---------------------------------------------------------------------------
def _patch_marker(monkeypatch, tmp_path: Path) -> Path:
    marker = tmp_path / "daemon.spawn"
    monkeypatch.setattr(render_thin, "_SPAWN_MARKER", marker)
    return marker


def test_spawn_debounce_allows_first_blocks_second(monkeypatch, tmp_path: Path):
    marker = _patch_marker(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(_d, "spawn_if_dead", lambda *a, **k: calls.append(1) or True)
    render_thin._spawn_daemon_async()
    render_thin._spawn_daemon_async()
    render_thin._spawn_daemon_async()
    assert len(calls) == 1
    assert marker.exists()


def test_spawn_debounce_expires_after_window(monkeypatch, tmp_path: Path):
    marker = _patch_marker(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(_d, "spawn_if_dead", lambda *a, **k: calls.append(1) or True)
    render_thin._spawn_daemon_async()
    # Age the marker past the debounce window.
    old = time.time() - render_thin._SPAWN_DEBOUNCE_S - 5
    os.utime(marker, (old, old))
    render_thin._spawn_daemon_async()
    assert len(calls) == 2


def test_spawn_debounce_future_mtime_self_heals(monkeypatch, tmp_path: Path):
    # Clock skew: marker stamped "in the future" must not wedge the
    # decision either way — it spawns once and re-touches the marker.
    marker = _patch_marker(monkeypatch, tmp_path)
    marker.touch()
    future = time.time() + 3600
    os.utime(marker, (future, future))
    calls = []
    monkeypatch.setattr(_d, "spawn_if_dead", lambda *a, **k: calls.append(1) or True)
    render_thin._spawn_daemon_async()
    assert len(calls) == 1
    assert marker.stat().st_mtime <= time.time() + 1  # re-stamped to now
    render_thin._spawn_daemon_async()
    assert len(calls) == 1  # and debounced again


def test_spawn_attempt_recorded_even_when_spawn_raises(monkeypatch, tmp_path: Path):
    # A failing spawn must still consume its debounce slot — a repeatedly
    # crashing spawn path is exactly the leak we're bounding.
    marker = _patch_marker(monkeypatch, tmp_path)

    def boom(*a, **k):
        raise RuntimeError("spawn exploded")

    monkeypatch.setattr(_d, "spawn_if_dead", boom)
    render_thin._spawn_daemon_async()  # exception swallowed
    assert marker.exists()
    calls = []
    monkeypatch.setattr(_d, "spawn_if_dead", lambda *a, **k: calls.append(1))
    render_thin._spawn_daemon_async()
    assert calls == []  # still inside the debounce window


def test_spawn_debounce_missing_marker_spawns(monkeypatch, tmp_path: Path):
    _patch_marker(monkeypatch, tmp_path)
    assert render_thin._spawn_recently_attempted() is False
