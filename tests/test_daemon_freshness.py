"""When the on-disk package is newer than the running daemon, the thin
client must treat the daemon's output as stale (force inline fallback +
re-spawn) so a PyPI auto-upgrade actually reaches the user."""
import json
import os
import signal
import time
from pathlib import Path
from unittest.mock import patch

import pytest


from claude_statusbar import render_thin
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
    can bring up a fresh one. The pidfile-check guard prevents signalling
    an unrelated process if the pid got reused."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(render_thin, "_pkg_mtime", lambda: time.time())
    meta = {
        "generated_at": time.time(),
        "stale_after_seconds": 5.0,
        "daemon_started_at": time.time() - 3600,
        "pid": 99999,  # a pid we will mock
    }
    with patch("os.kill") as kill:
        render_thin._signal_outdated_daemon(meta)
    kill.assert_called_once_with(99999, signal.SIGTERM)


def test_signal_outdated_daemon_swallows_errors(monkeypatch):
    """Pid may have died already; signalling should never raise."""
    meta = {"pid": 1}
    def _raise(*_):
        raise ProcessLookupError
    monkeypatch.setattr("os.kill", _raise)
    render_thin._signal_outdated_daemon(meta)  # must not raise
