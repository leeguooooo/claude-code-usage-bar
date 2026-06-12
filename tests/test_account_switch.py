# Account switch must not leak the previous account's 5h/7d readings.
#
# Live incident 2026-06-11: user switched Claude accounts; the bar kept showing
# the OLD account's seven_day 15% (and its learned →NN% projection) because
# rate_latest.json / rate_projection.json are account-global with no account
# key — the old reading's later resets_at won every monotonic merge until the
# old window expired (days). Stores are now keyed by oauthAccount.accountUuid
# from ~/.claude.json.
import json
import os

import claude_statusbar.predict as predict
from claude_statusbar.predict import reconcile_account


def _fake_claude_json(tmp_path, uuid, mtime=None):
    p = tmp_path / "claude.json"
    p.write_text(json.dumps({
        "someOtherState": {"x": 1},
        "oauthAccount": {"accountUuid": uuid, "emailAddress": "a@b.c"},
    }))
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


# --- account_id: parse + memoization ---

def test_account_id_reads_oauth_account_uuid(tmp_path, monkeypatch):
    p = _fake_claude_json(tmp_path, "cd5174d3-1111-2222-3333-444455556666", mtime=1000)
    monkeypatch.setattr(predict, "_CLAUDE_JSON_PATH", p)
    monkeypatch.setattr(predict, "_ACCOUNT_CACHE", {"sig": None, "id": None})
    assert predict._read_account_id() == "cd5174d3-1111-2222-3333-444455556666"


def test_account_id_tracks_file_change(tmp_path, monkeypatch):
    p = _fake_claude_json(tmp_path, "cd5174d3-1111-2222-3333-444455556666", mtime=1000)
    monkeypatch.setattr(predict, "_CLAUDE_JSON_PATH", p)
    monkeypatch.setattr(predict, "_ACCOUNT_CACHE", {"sig": None, "id": None})
    assert predict._read_account_id() == "cd5174d3-1111-2222-3333-444455556666"
    # same length uuid → same file size; mtime must invalidate the memo
    _fake_claude_json(tmp_path, "9e8f7a6b-1111-2222-3333-444455556666", mtime=2000)
    assert predict._read_account_id() == "9e8f7a6b-1111-2222-3333-444455556666"


def test_account_id_missing_file_is_none(tmp_path, monkeypatch):
    monkeypatch.setattr(predict, "_CLAUDE_JSON_PATH", tmp_path / "nope.json")
    monkeypatch.setattr(predict, "_ACCOUNT_CACHE", {"sig": None, "id": None})
    assert predict._read_account_id() is None


# --- per-account store isolation ---

def test_account_switch_does_not_leak_previous_readings(tmp_path, monkeypatch):
    """The bug: old account's seven_day reading has a LATER resets_at, so it
    won the monotonic merge against the new account's fresh (lower, earlier-
    reset) reading. With per-account stores the new account starts clean."""
    monkeypatch.setattr(predict, "_LATEST_PATH", tmp_path / "rate_latest.json")
    now = 1_781_000_000.0
    monkeypatch.setattr(predict, "account_id", lambda: "old-account-uuid-1234")
    reconcile_account(42.0, now + 3600, 15.0, now + 6 * 86400, now=now)
    # switch accounts: fresh account, lower 7d used, EARLIER reset
    monkeypatch.setattr(predict, "account_id", lambda: "new-account-uuid-5678")
    u5, r5, u7, r7 = reconcile_account(
        0.0, now + 17000, 2.0, now + 4 * 86400, now=now + 60)
    assert u7 == 2.0
    assert r7 == now + 4 * 86400
    assert u5 == 0.0


def test_switch_back_restores_own_account_data(tmp_path, monkeypatch):
    monkeypatch.setattr(predict, "_LATEST_PATH", tmp_path / "rate_latest.json")
    now = 1_781_000_000.0
    monkeypatch.setattr(predict, "account_id", lambda: "acct-a")
    reconcile_account(50.0, now + 3600, 30.0, now + 6 * 86400, now=now)
    monkeypatch.setattr(predict, "account_id", lambda: "acct-b")
    reconcile_account(1.0, now + 3600, 1.0, now + 5 * 86400, now=now)
    # back to A: its store still has the higher reading; a stale lower input
    # for the same resets must not win (normal monotonic behaviour preserved)
    monkeypatch.setattr(predict, "account_id", lambda: "acct-a")
    _, _, u7, _ = reconcile_account(50.0, now + 3600, 10.0, now + 6 * 86400,
                                    now=now + 5)
    assert u7 == 30.0


def test_unknown_account_uses_legacy_path(tmp_path, monkeypatch):
    """account undetectable (no ~/.claude.json) → exact legacy file, so
    behaviour is unchanged for API-key/headless users."""
    legacy = tmp_path / "rate_latest.json"
    monkeypatch.setattr(predict, "_LATEST_PATH", legacy)
    monkeypatch.setattr(predict, "account_id", lambda: None)
    now = 1_781_000_000.0
    r7 = now + 6 * 86400
    reconcile_account(10.0, now + 3600, 8.0, r7, now=now)
    assert legacy.exists()
    data = json.loads(legacy.read_text())
    # per-reset bucket schema: {window: {"<int reset>": {used, observed_at}}}
    assert data["seven_day"][str(int(r7))]["used"] == 8.0


def test_projection_store_is_per_account(tmp_path, monkeypatch):
    monkeypatch.setattr(predict, "_PROJECTION_PATH", tmp_path / "rate_projection.json")
    monkeypatch.setattr(predict, "account_id", lambda: "acct-a")
    store = predict.empty_projection_store()
    store["five_hour"] = [{"observed_at": 1.0, "used_pct": 5.0, "resets_at": 100.0,
                           "session_id": "s"}]
    predict.save_projection_store(store)
    # account A sees its own samples back
    assert predict.load_projection_store()["five_hour"]
    # account B starts with an empty store — no leaked learning
    monkeypatch.setattr(predict, "account_id", lambda: "acct-b")
    assert predict.load_projection_store()["five_hour"] == []
