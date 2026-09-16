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
from pathlib import Path

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
    monkeypatch.setattr(predict, "account_id", lambda *a, **k: "old-account-uuid-1234")
    reconcile_account(42.0, now + 3600, 15.0, now + 6 * 86400, now=now)
    # switch accounts: fresh account, lower 7d used, EARLIER reset
    monkeypatch.setattr(predict, "account_id", lambda *a, **k: "new-account-uuid-5678")
    u5, r5, u7, r7 = reconcile_account(
        0.0, now + 17000, 2.0, now + 4 * 86400, now=now + 60)
    assert u7 == 2.0
    assert r7 == now + 4 * 86400
    assert u5 == 0.0


def test_switch_back_restores_own_account_data(tmp_path, monkeypatch):
    monkeypatch.setattr(predict, "_LATEST_PATH", tmp_path / "rate_latest.json")
    now = 1_781_000_000.0
    monkeypatch.setattr(predict, "account_id", lambda *a, **k: "acct-a")
    reconcile_account(50.0, now + 3600, 30.0, now + 6 * 86400, now=now)
    monkeypatch.setattr(predict, "account_id", lambda *a, **k: "acct-b")
    reconcile_account(1.0, now + 3600, 1.0, now + 5 * 86400, now=now)
    # back to A: its store still has the higher reading; a stale lower input
    # for the same resets must not win (normal monotonic behaviour preserved)
    monkeypatch.setattr(predict, "account_id", lambda *a, **k: "acct-a")
    _, _, u7, _ = reconcile_account(50.0, now + 3600, 10.0, now + 6 * 86400,
                                    now=now + 5)
    assert u7 == 30.0


def test_unknown_account_uses_legacy_path(tmp_path, monkeypatch):
    """account undetectable (no ~/.claude.json) → exact legacy file, so
    behaviour is unchanged for API-key/headless users."""
    legacy = tmp_path / "rate_latest.json"
    monkeypatch.setattr(predict, "_LATEST_PATH", legacy)
    monkeypatch.setattr(predict, "account_id", lambda *a, **k: None)
    now = 1_781_000_000.0
    r7 = now + 6 * 86400
    reconcile_account(10.0, now + 3600, 8.0, r7, now=now)
    assert legacy.exists()
    data = json.loads(legacy.read_text())
    # per-reset bucket schema: {window: {"<int reset>": {used, observed_at}}}
    assert data["seven_day"][str(int(r7))]["used"] == 8.0


def test_projection_store_is_per_account(tmp_path, monkeypatch):
    monkeypatch.setattr(predict, "_PROJECTION_PATH", tmp_path / "rate_projection.json")
    monkeypatch.setattr(predict, "account_id", lambda *a, **k: "acct-a")
    store = predict.empty_projection_store()
    store["five_hour"] = [{"observed_at": 1.0, "used_pct": 5.0, "resets_at": 100.0,
                           "session_id": "s"}]
    predict.save_projection_store(store)
    # account A sees its own samples back
    assert predict.load_projection_store()["five_hour"]
    # account B starts with an empty store — no leaked learning
    monkeypatch.setattr(predict, "account_id", lambda *a, **k: "acct-b")
    assert predict.load_projection_store()["five_hour"] == []


# --- config dir: a second profile is a second account ---
#
# CLAUDE_CONFIG_DIR puts a whole second profile (its own login) under e.g.
# ~/.claude-work, so ~/.claude.json is NOT that session's identity file. Both
# profiles resolved to the DEFAULT account's uuid and shared one rate_latest
# bucket: whichever rendered last set both bars. The forecast spec already
# promised the store "respects CLAUDE_CONFIG_DIR/HOME"; the code never read it.
#
# The daemon renders many sessions inside ONE long-lived process, so its own
# environment names the daemon's profile, not the session's — the per-session
# config dir has to come from the payload. Claude Code writes transcripts to
# <config dir>/projects/<slug>/<session>.jsonl, which core already parses.

def _profile(tmp_path, name, uuid):
    """A config dir laid out like Claude Code's, with a transcript inside it."""
    cfg = tmp_path / name
    transcript = cfg / "projects" / "-home-u-proj" / "sess.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text("")
    (cfg / ".claude.json").write_text(json.dumps({
        "oauthAccount": {"accountUuid": uuid, "emailAddress": "a@b.c"},
    }))
    return cfg, transcript


def test_account_id_from_transcript_path(tmp_path, monkeypatch):
    _, personal = _profile(tmp_path, ".claude", "aaaaaaaa-1111-2222-3333-444455556666")
    _, work = _profile(tmp_path, ".claude-work", "bbbbbbbb-1111-2222-3333-444455556666")
    monkeypatch.setattr(predict, "_ACCOUNT_CACHE", {"sig": None, "id": None})
    assert predict._read_account_id(str(personal)) == "aaaaaaaa-1111-2222-3333-444455556666"
    # same file size → only the path may invalidate the memo
    assert predict._read_account_id(str(work)) == "bbbbbbbb-1111-2222-3333-444455556666"


def test_two_profiles_do_not_share_a_bucket(tmp_path, monkeypatch):
    """The reported bug: the work profile's reading landed in the personal
    account's store, so the last session to render set both bars."""
    _, personal = _profile(tmp_path, ".claude", "aaaaaaaa-1111-2222-3333-444455556666")
    _, work = _profile(tmp_path, ".claude-work", "bbbbbbbb-1111-2222-3333-444455556666")
    monkeypatch.setattr(predict, "_LATEST_PATH", tmp_path / "rate_latest.json")
    monkeypatch.setattr(predict, "_ACCOUNT_CACHE", {"sig": None, "id": None})
    monkeypatch.setattr(predict, "account_id", predict._read_account_id)
    now = 1_781_000_000.0
    reconcile_account(80.0, now + 3600, 70.0, now + 6 * 86400, now=now,
                      transcript_path=str(personal))
    _, _, u7, _ = reconcile_account(1.0, now + 3600, 2.0, now + 6 * 86400,
                                    now=now + 60, transcript_path=str(work))
    assert u7 == 2.0


def test_no_transcript_falls_back_to_the_default_path(tmp_path, monkeypatch):
    """Callers without a payload (doctor, background collectors) keep reading
    the module-level path, which resolves CLAUDE_CONFIG_DIR at import."""
    monkeypatch.setattr(predict, "_ACCOUNT_CACHE", {"sig": None, "id": None})
    monkeypatch.setattr(predict, "_CLAUDE_JSON_PATH",
                        _fake_claude_json(tmp_path, "cccccccc-1111-2222-3333-444455556666"))
    assert predict._read_account_id() == "cccccccc-1111-2222-3333-444455556666"


def test_default_path_honours_config_dir_env(tmp_path, monkeypatch):
    cfg, _ = _profile(tmp_path, ".claude-work", "bbbbbbbb-1111-2222-3333-444455556666")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    assert predict._default_claude_json_path() == cfg / ".claude.json"
    monkeypatch.delenv("CLAUDE_CONFIG_DIR")
    assert predict._default_claude_json_path() == \
        Path(os.path.expanduser("~")) / ".claude.json"


def test_unplaceable_transcript_claims_no_account(tmp_path, monkeypatch):
    """A path that isn't <config>/projects/<slug>/<id>.jsonl leaves the account
    unknown. Falling back to the ambient profile would write this session into
    a real account's store — the assumption that caused the shared bucket. The
    legacy unsuffixed store is the existing home for an unknown account."""
    monkeypatch.setattr(predict, "_ACCOUNT_CACHE", {"sig": None, "id": None})
    monkeypatch.setattr(predict, "_CLAUDE_JSON_PATH",
                        _fake_claude_json(tmp_path, "cccccccc-1111-2222-3333-444455556666"))
    monkeypatch.setattr(predict, "account_id", predict._read_account_id)
    assert predict._read_account_id("/var/log/elsewhere/sess.jsonl") is None
    monkeypatch.setattr(predict, "_LATEST_PATH", tmp_path / "rate_latest.json")
    assert predict._latest_path("/var/log/elsewhere/sess.jsonl") == \
        tmp_path / "rate_latest.json"
    # no payload at all still means "this machine's default profile"
    assert predict._read_account_id() == "cccccccc-1111-2222-3333-444455556666"


def test_two_profiles_do_not_share_projection_history(tmp_path, monkeypatch):
    """The projection store and its 1s result cache are account-keyed too, so
    they need the session's config dir for the same reason the latest store
    does — otherwise one daemon process serves profile A's learned →NN% to
    profile B."""
    _, personal = _profile(tmp_path, ".claude", "aaaaaaaa-1111-2222-3333-444455556666")
    _, work = _profile(tmp_path, ".claude-work", "bbbbbbbb-1111-2222-3333-444455556666")
    monkeypatch.setattr(predict, "_LATEST_PATH", tmp_path / "rate_latest.json")
    monkeypatch.setattr(predict, "_PROJECTION_PATH", tmp_path / "rate_projection.json")
    monkeypatch.setattr(predict, "_ACCOUNT_CACHE", {"sig": None, "id": None})
    monkeypatch.setattr(predict, "account_id", predict._read_account_id)

    assert predict._projection_path(str(personal)) != predict._projection_path(str(work))
    # the 1s result cache keys on both store paths, so it can't cross profiles
    key_p = predict._projection_result_key(1.0, 2.0, 3.0, 4.0, str(personal))
    key_w = predict._projection_result_key(1.0, 2.0, 3.0, 4.0, str(work))
    assert key_p != key_w

    store = predict.empty_projection_store()
    store["five_hour"] = [{"observed_at": 1.0, "used_pct": 5.0, "resets_at": 100.0,
                           "session_id": "s"}]
    predict.save_projection_store(store, transcript_path=str(personal))
    assert predict.load_projection_store(transcript_path=str(personal))["five_hour"]
    assert predict.load_projection_store(transcript_path=str(work))["five_hour"] == []


def test_default_profile_login_sits_beside_its_config_dir(tmp_path, monkeypatch):
    """The two layouts differ: a CLAUDE_CONFIG_DIR profile keeps its login
    INSIDE the dir, but the default profile keeps transcripts in ~/.claude/ and
    its login at ~/.claude.json, BESIDE it. Deriving <config dir>/.claude.json
    alone left every ordinary user accountless and back in the legacy bucket —
    while their transcript-less background collectors still resolved the uuid
    and wrote to the suffixed store, splitting one account across two files."""
    uuid = "dddddddd-1111-2222-3333-444455556666"
    (tmp_path / ".claude.json").write_text(json.dumps({
        "oauthAccount": {"accountUuid": uuid, "emailAddress": "a@b.c"},
    }))
    transcript = tmp_path / ".claude" / "projects" / "-home-u-proj" / "sess.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text("")
    monkeypatch.setattr(predict, "_ACCOUNT_CACHE", {"sig": None, "id": None})
    monkeypatch.setattr(predict, "_CLAUDE_JSON_PATH", tmp_path / ".claude.json")
    monkeypatch.setattr(predict, "account_id", predict._read_account_id)
    monkeypatch.setattr(predict, "_LATEST_PATH", tmp_path / "rate_latest.json")

    assert predict._read_account_id(str(transcript)) == uuid
    # the session and the transcript-less collectors agree on one store
    assert predict._latest_path(str(transcript)) == predict._latest_path()

    # a config-dir profile still wins with its own in-dir login
    _, work = _profile(tmp_path, ".claude-work", "bbbbbbbb-1111-2222-3333-444455556666")
    assert predict._read_account_id(str(work)) == "bbbbbbbb-1111-2222-3333-444455556666"
