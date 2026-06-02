"""check_for_updates rate-limits to one check per machine per 24h AND never
runs the upgrade synchronously — it spawns a detached background process so a
slow `uv tool install` can't block a status-line render.

Reasons:
  1. Auto-update is slow (network + install). Running it inline would freeze
     the triggering render for tens of seconds.
  2. Opening N Claude Code windows at once must not fire N parallel installs.
"""

import pytest

from claude_statusbar import core


@pytest.fixture
def isolated_cache(monkeypatch, tmp_path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(core.Path, "home", classmethod(lambda cls: fake_home))
    return fake_home


def test_marker_touched_before_spawn(isolated_cache, monkeypatch):
    """Even if the spawn raises, the marker must already be fresh so the next
    render skips the re-check."""
    marker = isolated_cache / ".cache" / "claude-statusbar" / "last_update_check"

    class Hang(Exception):
        pass

    def fake_spawn():
        assert marker.exists(), "marker not touched before spawn"
        raise Hang("simulated")

    import claude_statusbar.updater as updater
    monkeypatch.setattr(updater, "spawn_background_upgrade_check", fake_spawn)
    core.check_for_updates(session_id="anything")  # must not raise
    assert marker.exists()


def test_spawns_detached_never_runs_sync(isolated_cache, monkeypatch):
    """Must SPAWN a background upgrade, never run check_and_upgrade inline."""
    import claude_statusbar.updater as updater
    spawned = []
    monkeypatch.setattr(updater, "spawn_background_upgrade_check",
                        lambda: spawned.append(1))
    monkeypatch.setattr(updater, "check_and_upgrade",
                        lambda: (_ for _ in ()).throw(AssertionError("ran sync")))
    core.check_for_updates(session_id="x")
    assert spawned == [1]


def test_skips_when_marker_is_fresh(isolated_cache, monkeypatch):
    cache_dir = isolated_cache / ".cache" / "claude-statusbar"
    cache_dir.mkdir(parents=True)
    (cache_dir / "last_update_check").touch()  # fresh = now

    called = []
    import claude_statusbar.updater as updater
    monkeypatch.setattr(updater, "spawn_background_upgrade_check",
                        lambda: called.append(1))
    core.check_for_updates(session_id="x")
    assert called == []


def test_runs_when_marker_is_old(isolated_cache, monkeypatch):
    import os
    cache_dir = isolated_cache / ".cache" / "claude-statusbar"
    cache_dir.mkdir(parents=True)
    marker = cache_dir / "last_update_check"
    marker.touch()
    old = marker.stat().st_mtime - 25 * 3600
    os.utime(marker, (old, old))

    called = []
    import claude_statusbar.updater as updater
    monkeypatch.setattr(updater, "spawn_background_upgrade_check",
                        lambda: called.append(1))
    core.check_for_updates(session_id="x")
    assert called == [1]


def test_concurrent_sessions_only_one_checks(isolated_cache, monkeypatch):
    """N back-to-back invocations → only one spawn (rest see fresh marker)."""
    counter = [0]
    import claude_statusbar.updater as updater
    monkeypatch.setattr(updater, "spawn_background_upgrade_check",
                        lambda: counter.__setitem__(0, counter[0] + 1))
    for sid in ("A", "B", "C", "D", "E"):
        core.check_for_updates(session_id=sid)
    assert counter[0] == 1


def test_opt_out_via_env_var(isolated_cache, monkeypatch):
    monkeypatch.setenv("CLAUDE_STATUSBAR_NO_UPDATE", "1")
    called = []
    import claude_statusbar.updater as updater
    monkeypatch.setattr(updater, "spawn_background_upgrade_check",
                        lambda: called.append(1))
    core.check_for_updates(session_id="anything")
    assert called == []


def test_spawn_background_upgrade_check_is_detached(monkeypatch):
    """Launches `python -m claude_statusbar.updater` detached; never raises."""
    import claude_statusbar.updater as updater
    captured = {}

    class FakePopen:
        def __init__(self, cmd, **kw):
            captured["cmd"] = cmd
            captured["kw"] = kw

    monkeypatch.setattr(updater.subprocess, "Popen", FakePopen)
    updater.spawn_background_upgrade_check()
    assert captured["cmd"][1:] == ["-m", "claude_statusbar.updater"]
    assert captured["kw"].get("start_new_session") is True

    def boom(*a, **k):
        raise OSError("no fork")
    monkeypatch.setattr(updater.subprocess, "Popen", boom)
    updater.spawn_background_upgrade_check()  # swallowed, no raise
