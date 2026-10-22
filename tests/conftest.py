import pytest


@pytest.fixture(autouse=True)
def _isolate_rate_latest(tmp_path, monkeypatch):
    """Keep every test off the real ~/.cache/claude-statusbar/rate_latest.json.

    predict.reconcile_account (reached via forecast() and core.main's render
    path) reads+writes that shared account-global store. Without isolation tests
    would pollute the developer's real cache and leak state into each other.
    Each test gets its own throwaway path."""
    try:
        import claude_statusbar.predict as predict
        monkeypatch.setattr(predict, "_LATEST_PATH", tmp_path / "rate_latest.json")
        monkeypatch.setattr(predict, "_PROJECTION_PATH", tmp_path / "rate_projection.json")
        # Stores are account-keyed (suffix from ~/.claude.json); pin the
        # account to "unknown" so tests get the exact paths they monkeypatch,
        # independent of the developer's real login. Account-switch tests
        # override this stub locally.
        monkeypatch.setattr(predict, "account_id", lambda *a, **k: None)
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _isolate_ocs(tmp_path, monkeypatch):
    """core renders with show_ocs on by default: without this, any test that
    passes a session_id would spawn the developer's real `ocs` and write to
    the real ~/.cache/claude-statusbar/ocs. test_ocs.py re-enables find_ocs
    against a fake binary."""
    try:
        import claude_statusbar.ocs as ocs
        monkeypatch.setattr(ocs, "_cache_root", lambda: tmp_path / "ocs-cache")
        monkeypatch.setattr(ocs, "find_ocs", lambda: None)
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _isolate_render_sessions(tmp_path, monkeypatch):
    """Config writes invalidate session renders; keep that off the real cache."""
    from claude_statusbar import render_thin
    monkeypatch.setattr(render_thin, "_SESSIONS_DIR", tmp_path / "render-sessions")


@pytest.fixture(autouse=True)
def _isolate_ip_risk_cache(tmp_path, monkeypatch):
    """Doctor/render tests must not consult a developer's real IP history."""
    from claude_statusbar import ip_risk
    monkeypatch.setattr(ip_risk, "_cache_root", lambda: tmp_path / "ip-risk-cache")


@pytest.fixture(autouse=True)
def _isolate_upgrade_daemon(tmp_path, monkeypatch):
    """Upgrade tests must never see — or restart — the developer's real daemon."""
    from claude_statusbar import updater
    monkeypatch.setattr(updater, "_daemon_alive", lambda: False)
    monkeypatch.setattr(updater, "_restart_daemon_only",
                        lambda: (False, "restart disabled in tests"))
    monkeypatch.setattr(updater, "UPGRADE_STATUS", tmp_path / "upgrade_status.json")
    # get_latest_version / latest_release_tag cache what they resolve; tests
    # that fake those responses must not rewrite the real ↑-hint cache.
    monkeypatch.setattr(updater, "LATEST_VERSION_CACHE", tmp_path / "latest_version.json")


@pytest.fixture(autouse=True)
def service_calls(monkeypatch):
    """No test may start, stop or reload the developer's real daemon service.

    `cs --setup` hands the daemon to launchd (`launchctl kickstart -k`, which
    kills and restarts the running daemon) or spawns one directly; both used to
    run for real from test_setup.py. Every launchctl / systemctl --user call
    and every daemon start is recorded here instead. Tests that exercise the
    service layer replace these with their own fakes.
    """
    from claude_statusbar import daemon, service
    calls = []

    def fake(tool):
        def run(*args):
            calls.append((tool, *args))
            return 1, "", f"{tool} blocked in tests"
        return run

    monkeypatch.setattr(service, "_launchctl", fake("launchctl"))
    monkeypatch.setattr(service, "_systemctl_user", fake("systemctl"))
    monkeypatch.setattr(daemon, "cmd_start",
                        lambda *a, **k: calls.append(("cmd_start", k)) or 0)
    return calls
