"""An upgrade that installed but whose daemon didn't come back retries only
the restart, never the install, and says so."""
import json

import pytest

from claude_statusbar import updater


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "UPGRADE_STATUS", tmp_path / "upgrade_status.json")
    monkeypatch.setattr(updater, "_RESTART_WAIT_S", 0)
    monkeypatch.setattr(updater, "installed_version_on_path", lambda: "9.9.9")
    calls = {"restart": 0}

    def restart():
        calls["restart"] += 1
        return True, "ok"
    monkeypatch.setattr(updater, "_restart_daemon_only", restart)
    return tmp_path, calls


def _status(tmp_path):
    return json.loads((tmp_path / "upgrade_status.json").read_text())


def test_daemon_back_on_its_own(env, monkeypatch):
    tmp_path, calls = env
    monkeypatch.setattr(updater, "_daemon_started_since", lambda t0: True)
    assert updater.settle_daemon(0, True) == ("restarted", "")
    assert calls["restart"] == 0
    assert _status(tmp_path)["daemon"] == "restarted"


def test_restart_retry_recovers(env, monkeypatch):
    tmp_path, calls = env
    seq = iter([False, True])
    monkeypatch.setattr(updater, "_daemon_started_since", lambda t0: next(seq))
    state, detail = updater.settle_daemon(0, True)
    assert (state, detail) == ("restarted", "after 1 restart retry")
    assert calls["restart"] == 1


def test_restart_failure_is_recorded(env, monkeypatch):
    tmp_path, calls = env
    monkeypatch.setattr(updater, "_daemon_started_since", lambda t0: False)
    state, detail = updater.settle_daemon(0, True)
    assert state == "restart_failed" and calls["restart"] == updater._RESTART_RETRIES
    st = _status(tmp_path)
    assert st["daemon"] == "restart_failed" and st["version"] == "9.9.9"


def test_no_daemon_before_means_nothing_to_restart(env, monkeypatch):
    tmp_path, calls = env
    monkeypatch.setattr(updater, "_daemon_started_since", lambda t0: pytest.fail("no wait"))
    assert updater.settle_daemon(0, False)[0] == "not_running"
    assert calls["restart"] == 0


def test_auto_upgrade_never_reinstalls_for_a_failed_restart(env, monkeypatch):
    runs = []
    monkeypatch.setattr(updater, "is_shadow_install", lambda: False)
    monkeypatch.setattr(updater, "_windows_in_place", lambda: False)
    monkeypatch.setattr(updater, "_is_frozen", lambda: True)
    monkeypatch.setattr(updater, "resolve_latest_version", lambda: "9.9.9")
    monkeypatch.setattr(updater, "get_current_version", lambda: "9.9.8")
    monkeypatch.setattr(updater, "_run_installer", lambda v: runs.append(v) or True)
    monkeypatch.setattr(updater, "_daemon_alive", lambda: True)
    monkeypatch.setattr(updater, "_daemon_started_since", lambda t0: False)
    assert updater.auto_upgrade() is True       # installed counts as upgraded
    assert runs == ["9.9.9"]                    # exactly one install


def test_cs_upgrade_reports_installed_but_restart_failed(env, monkeypatch):
    monkeypatch.setattr(updater, "_is_frozen", lambda: True)
    monkeypatch.setattr(updater, "resolve_latest_version", lambda: "9.9.9")
    monkeypatch.setattr(updater, "get_current_version", lambda: "9.9.8")
    monkeypatch.setattr(updater, "_run_installer", lambda v: True)
    monkeypatch.setattr(updater, "_daemon_alive", lambda: True)
    monkeypatch.setattr(updater, "_daemon_started_since", lambda t0: False)
    monkeypatch.setattr(updater, "restart_hint", lambda: "cs daemon install")
    ok, msg = updater.upgrade_current_install()
    assert ok is False
    assert msg.startswith("Installed v9.9.9, but the background daemon did not restart")
    assert "without reinstalling" in msg and "cs daemon install" in msg
