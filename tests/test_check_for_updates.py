"""check_for_updates must record the session ID BEFORE running the upgrade.

If a hung pip/uv freezes the upgrade subprocess, the user kills cs and
restarts. On restart we MUST not retry the same upgrade — that would loop
the freeze. Marking the session as checked first is the guard.
"""

from pathlib import Path

import pytest

from claude_statusbar import core


@pytest.fixture
def isolated_cache(monkeypatch, tmp_path):
    """Redirect the .cache/claude-statusbar directory used by check_for_updates."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(core.Path, "home", classmethod(lambda cls: fake_home))
    return fake_home


def test_session_marked_before_upgrade_runs(isolated_cache, monkeypatch):
    """If the upgrade hangs (raises), the session file must already be written
    so that the next render skips the check."""
    home = isolated_cache
    cache_file = home / ".cache" / "claude-statusbar" / "last_update_session"

    class Hang(Exception):
        pass

    def fake_check_and_upgrade():
        # By the time we get here, the session must already be recorded.
        assert cache_file.exists(), "session file written too late!"
        raise Hang("simulated hang")

    # Patch the import target inside core.check_for_updates
    import claude_statusbar.updater as updater
    monkeypatch.setattr(updater, "check_and_upgrade", fake_check_and_upgrade)

    # check_for_updates swallows exceptions, so this must NOT raise.
    core.check_for_updates(session_id="session-123")

    assert cache_file.exists()
    assert cache_file.read_text(encoding="utf-8").strip() == "session-123"


def test_no_check_when_session_already_seen(isolated_cache, monkeypatch):
    """Same session_id → don't call check_and_upgrade again."""
    home = isolated_cache
    cache_dir = home / ".cache" / "claude-statusbar"
    cache_dir.mkdir(parents=True)
    (cache_dir / "last_update_session").write_text("session-X", encoding="utf-8")

    called = []
    import claude_statusbar.updater as updater
    monkeypatch.setattr(updater, "check_and_upgrade",
                         lambda: called.append("yes") or (False, "ok"))

    core.check_for_updates(session_id="session-X")
    assert called == [], "should not have called check_and_upgrade"


def test_opt_out_via_env_var(isolated_cache, monkeypatch):
    monkeypatch.setenv("CLAUDE_STATUSBAR_NO_UPDATE", "1")
    called = []
    import claude_statusbar.updater as updater
    monkeypatch.setattr(updater, "check_and_upgrade",
                         lambda: called.append("yes") or (False, "ok"))
    core.check_for_updates(session_id="anything")
    assert called == []
