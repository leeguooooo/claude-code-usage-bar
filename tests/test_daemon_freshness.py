"""When the on-disk package is newer than the running daemon, the thin
client must treat the daemon's output as stale (force inline fallback +
re-spawn) so a PyPI auto-upgrade actually reaches the user."""
import json
import os
import signal
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest


from claude_statusbar import daemon, render_thin
from claude_statusbar.daemon import session_meta_path, session_rendered_path


def _write_session(tmp_home, sid, *, daemon_started_at, ansi="hello"):
    """Set up a session bucket with a meta + rendered.ansi, controlling
    `daemon_started_at`."""
    sess = tmp_home / ".cache" / "claude-statusbar" / "sessions" / sid
    sess.mkdir(parents=True, exist_ok=True)
    (sess / "rendered.ansi").write_text(ansi, encoding="utf-8")
    (sess / "rendered.meta.json").write_text(json.dumps({
        "generated_at": time.time(),
        "pid": os.getpid(),
        "stale_after_seconds": 5.0,
        "session_id": sid,
        "daemon_started_at": daemon_started_at,
    }), encoding="utf-8")


def test_meta_with_recent_daemon_is_fresh(tmp_path, monkeypatch):
    """Sanity: when daemon_started_at is newer than the package mtime, the
    thin client treats meta as fresh (today's daemon, today's code)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    meta = {
        "generated_at": time.time(),
        "stale_after_seconds": 5.0,
        "daemon_started_at": time.time(),  # daemon started just now
    }
    assert render_thin._is_fresh(meta) is True


def test_meta_with_outdated_daemon_is_stale(monkeypatch):
    """Core invariant: if the installed code is newer than the daemon's
    boot time, the meta is stale even if generated_at is recent."""
    # Pretend the package directory's mtime is "just now"; the daemon
    # booted 1 hour ago, which is before the (fake) upgrade.
    fake_now = time.time()

    class _FakeStat:
        st_mtime = fake_now

    monkeypatch.setattr(render_thin, "_pkg_mtime", lambda: fake_now)
    meta = {
        "generated_at": fake_now,
        "stale_after_seconds": 5.0,
        "daemon_started_at": fake_now - 3600,
    }
    assert render_thin._is_fresh(meta) is False


def test_meta_without_daemon_started_at_falls_back_to_age_check(monkeypatch):
    """Older daemons (pre-3.8.1) don't write `daemon_started_at`. Thin
    client must not treat their absence as 'stale forever' — fall back
    to the existing age-only check so the upgrade rollout is smooth."""
    monkeypatch.setattr(render_thin, "_pkg_mtime", lambda: time.time())
    meta = {
        "generated_at": time.time(),
        "stale_after_seconds": 5.0,
        # NO daemon_started_at
    }
    assert render_thin._is_fresh(meta) is True


def test_outdated_daemon_signals_pid_to_exit(tmp_path, monkeypatch):
    """When the thin client decides the daemon is outdated, it should
    send SIGTERM to the pid recorded in the meta so launchd / lazy-spawn
    can bring up a fresh one."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(render_thin, "_pkg_mtime", lambda: time.time())
    monkeypatch.setattr(daemon, "_process_is_our_daemon", lambda pid: True)
    meta = {
        "generated_at": time.time(),
        "stale_after_seconds": 5.0,
        "daemon_started_at": time.time() - 3600,
        "pid": 99999,  # a pid we will mock
    }
    with patch("os.kill") as kill:
        render_thin._signal_outdated_daemon(meta)
    kill.assert_called_once_with(99999, signal.SIGTERM)


def test_recycled_pid_is_never_signalled(monkeypatch):
    """A session's meta outlives the daemon that wrote it, so meta["pid"] can
    point at an unrelated user process by the time we read it. Never SIGTERM
    a pid that is no longer our daemon."""
    monkeypatch.setattr(daemon, "_process_is_our_daemon", lambda pid: False)
    with patch("os.kill") as kill:
        render_thin._signal_outdated_daemon({"pid": 99999})
    kill.assert_not_called()


def test_signal_outdated_daemon_swallows_errors(monkeypatch):
    """Pid may have died already; signalling should never raise."""
    monkeypatch.setattr(daemon, "_process_is_our_daemon", lambda pid: True)
    meta = {"pid": 99999}
    def _raise(*_):
        raise ProcessLookupError
    monkeypatch.setattr("os.kill", _raise)
    render_thin._signal_outdated_daemon(meta)  # must not raise



# ---------------------------------------------------------------------------
# Issue #36: standalone PyInstaller binary crashed on every render once a
# daemon session was cached. `_pkg_mtime()` scanned the package dir for `.py`
# files; a frozen onefile build has none (modules live in the PYZ archive), so
# `max()` got an empty iterable and raised ValueError — which `except OSError`
# did not catch. Uncaught → statusline died on every tick.
# ---------------------------------------------------------------------------
def test_pkg_mtime_survives_package_dir_without_py_files(tmp_path, monkeypatch):
    """No .py files on disk must degrade to 0.0, never raise."""
    monkeypatch.setattr(render_thin, "_PKG_DIR", tmp_path)
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert render_thin._pkg_mtime() == 0.0


def test_is_outdated_daemon_does_not_raise_without_py_files(tmp_path, monkeypatch):
    """The exact crash path from the report: cached meta carrying
    `daemon_started_at` + a package dir with no .py files."""
    monkeypatch.setattr(render_thin, "_PKG_DIR", tmp_path)
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert render_thin._is_outdated_daemon({"daemon_started_at": 1.0}) is False


def test_frozen_build_uses_executable_mtime(tmp_path, monkeypatch):
    """Frozen binaries have no loose .py files, but the staleness feature must
    still work: re-running install.sh swaps the binary, so its mtime is the
    'installed code version'."""
    exe = tmp_path / "cs"
    exe.write_text("binary", encoding="utf-8")
    os.utime(exe, (1_000_000, 1_000_000))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    assert render_thin._pkg_mtime() == 1_000_000

    # A daemon started before that binary was installed is outdated...
    assert render_thin._is_outdated_daemon({"daemon_started_at": 999_999}) is True
    # ...and one started after it is not.
    assert render_thin._is_outdated_daemon({"daemon_started_at": 1_000_001}) is False


def test_frozen_build_with_missing_executable_degrades(tmp_path, monkeypatch):
    """stat() on a vanished/inaccessible binary must degrade, not raise."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "gone"))
    assert render_thin._pkg_mtime() == 0.0
