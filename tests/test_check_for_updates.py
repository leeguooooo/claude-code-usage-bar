"""check_for_updates rate-limits to one check per machine per 24h.

Two reasons matter:
  1. Auto-update is slow (network + pip). Doing it on every session start
     would block every fresh Claude Code window for several seconds.
  2. Opening N Claude Code windows simultaneously must not fire N parallel
     pip installs (used to be the case with the per-session_id gate).
"""

from pathlib import Path

import pytest

from claude_statusbar import core


@pytest.fixture
def isolated_cache(monkeypatch, tmp_path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(core.Path, "home", classmethod(lambda cls: fake_home))
    return fake_home


def test_marker_touched_before_upgrade_runs(isolated_cache, monkeypatch):
    """Even if the upgrade raises (hang / network), the marker must already
    be fresh so the next render skips the re-check."""
    home = isolated_cache
    marker = home / ".cache" / "claude-statusbar" / "last_update_check"

    class Hang(Exception): pass

    def fake_check_and_upgrade():
        assert marker.exists(), "marker not touched before upgrade"
        raise Hang("simulated")

    import claude_statusbar.updater as updater
    monkeypatch.setattr(updater, "check_and_upgrade", fake_check_and_upgrade)
    core.check_for_updates(session_id="anything")  # must not raise
    assert marker.exists()


def test_skips_when_marker_is_fresh(isolated_cache, monkeypatch):
    """Second call within the 24h window must not run the upgrade."""
    home = isolated_cache
    cache_dir = home / ".cache" / "claude-statusbar"
    cache_dir.mkdir(parents=True)
    marker = cache_dir / "last_update_check"
    marker.touch()  # fresh mtime = now

    called = []
    import claude_statusbar.updater as updater
    monkeypatch.setattr(updater, "check_and_upgrade",
                         lambda: called.append(1) or (False, ""))

    core.check_for_updates(session_id="x")
    assert called == []


def test_runs_when_marker_is_old(isolated_cache, monkeypatch):
    """Marker > 24h old must trigger another check."""
    home = isolated_cache
    cache_dir = home / ".cache" / "claude-statusbar"
    cache_dir.mkdir(parents=True)
    marker = cache_dir / "last_update_check"
    marker.touch()

    # Simulate marker stat returning 25h ago
    import os
    old_time = marker.stat().st_mtime - 25 * 3600
    os.utime(marker, (old_time, old_time))

    called = []
    import claude_statusbar.updater as updater
    monkeypatch.setattr(updater, "check_and_upgrade",
                         lambda: called.append(1) or (False, ""))

    core.check_for_updates(session_id="x")
    assert called == [1]


def test_concurrent_sessions_only_one_checks(isolated_cache, monkeypatch):
    """N back-to-back invocations of check_for_updates must result in only
    one underlying check_and_upgrade call (the rest see fresh marker and
    skip). Simulates N parallel Claude Code windows starting at once."""
    counter = [0]
    import claude_statusbar.updater as updater
    monkeypatch.setattr(updater, "check_and_upgrade",
                         lambda: (counter.__setitem__(0, counter[0] + 1) or (False, ""))[1])

    # First call should fire; subsequent calls in the same 24h window should not.
    for sid in ("sess-A", "sess-B", "sess-C", "sess-D", "sess-E"):
        core.check_for_updates(session_id=sid)
    assert counter[0] == 1, f"expected 1 check across 5 sessions, got {counter[0]}"


def test_opt_out_via_env_var(isolated_cache, monkeypatch):
    monkeypatch.setenv("CLAUDE_STATUSBAR_NO_UPDATE", "1")
    called = []
    import claude_statusbar.updater as updater
    monkeypatch.setattr(updater, "check_and_upgrade",
                         lambda: called.append(1) or (False, ""))
    core.check_for_updates(session_id="anything")
    assert called == []
