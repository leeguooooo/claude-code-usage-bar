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
        monkeypatch.setattr(predict, "account_id", lambda: None)
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
