"""Sessions without rate_limits borrow the account's last quota snapshot.

That snapshot is whatever any open window last wrote — often an idle one
replaying hours-old headers. Live 2026-11-19: four such sessions recorded the
flapping snapshot as their own fresh readings, re-confirming a pre-reset 97%
every render, so 7d stayed at 97% while the usage API said 0%.
"""
import io
import json
import time

from claude_statusbar import core, predict


def _run(monkeypatch, capsys, payload):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    monkeypatch.setattr("sys.stdin.isatty", lambda: False, raising=False)
    core.main(json_output=True, _suppress_side_effects=True)
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def test_borrowed_snapshot_neither_records_nor_outvotes_store(monkeypatch, capsys):
    now = time.time()
    reset = int(now + 3 * 86400)
    predict.reconcile_account(None, None, 1.0, reset, now=now, session_id="live")
    before = predict._LATEST_PATH.read_text()
    monkeypatch.setattr("claude_statusbar.quota_cache.read", lambda data: {
        "seven_day": {"used_percentage": 97, "resets_at": reset}})

    out = _run(monkeypatch, capsys, {"session_id": "borrower",
                                     "model": {"id": "claude-opus-5-5"}})

    assert out["rate_limits"]["seven_day"]["used_percentage"] == 1.0
    assert predict._LATEST_PATH.read_text() == before


def test_borrowed_snapshot_fills_in_when_store_is_empty(monkeypatch, capsys):
    reset = int(time.time() + 3 * 86400)
    monkeypatch.setattr("claude_statusbar.quota_cache.read", lambda data: {
        "seven_day": {"used_percentage": 40, "resets_at": reset}})

    out = _run(monkeypatch, capsys, {"session_id": "borrower"})

    assert out["rate_limits"]["seven_day"]["used_percentage"] == 40
    assert not predict._LATEST_PATH.exists()


def test_first_sighting_of_idle_window_cannot_lift_the_bar(tmp_path):
    """An idle window re-seen (entry aged out, daemon restart) replays old
    headers. Its transcript dates them: last written long ago → display only."""
    import os
    now = time.time()
    reset = now + 3 * 86400
    predict.reconcile_account(None, None, 3.0, reset, now=now, session_id="live")
    old = tmp_path / "idle.jsonl"
    old.write_text("{}\n")
    os.utime(old, (now - 2 * 3600, now - 2 * 3600))

    _, _, u7, _ = predict.reconcile_account(
        None, None, 31.0, reset, now=now + 1, session_id="idle",
        transcript_path=str(old))
    assert u7 == 3.0
    # Still frozen on the next render, and the entry stays (no re-sighting churn).
    _, _, u7, _ = predict.reconcile_account(
        None, None, 31.0, reset, now=now + 2, session_id="idle",
        transcript_path=str(old))
    assert u7 == 3.0


def test_first_sighting_of_new_session_is_fresh(tmp_path):
    now = time.time()
    reset = now + 3 * 86400
    predict.reconcile_account(None, None, 3.0, reset, now=now, session_id="live")
    fresh = tmp_path / "new.jsonl"
    fresh.write_text("{}\n")

    _, _, u7, _ = predict.reconcile_account(
        None, None, 5.0, reset, session_id="new", transcript_path=str(fresh))
    assert u7 == 5.0
