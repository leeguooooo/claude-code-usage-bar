"""Stale-quota classification + the `⟳ 5h/7d stale·restart` hint.

Regression cover for the "Pro user's bars silently vanished" failure: when the
statusLine pipeline stops feeding cs, the cached windows expire and used to be
dropped to two blank `--%` bars (indistinguishable from a fresh session). The
bar must now say it's stale, and only when the cache genuinely rotted.
"""
import json
import time

from claude_statusbar import predict, progress


def _write(path, store):
    path.write_text(json.dumps(store), encoding="utf-8")


def test_status_empty_when_no_store(tmp_path):
    assert predict.quota_cache_status(path=tmp_path / "nope.json") == ("empty", None)


def test_status_empty_for_empty_store(tmp_path):
    p = tmp_path / "s.json"
    _write(p, {})
    assert predict.quota_cache_status(path=p) == ("empty", None)


def test_status_fresh_when_reset_in_future(tmp_path):
    now = 1_000_000.0
    p = tmp_path / "s.json"
    _write(p, {"five_hour": {str(int(now + 3600)): {"used": 40, "observed_at": now - 5}}})
    status, age = predict.quota_cache_status(now=now, path=p)
    assert status == "fresh"
    assert age == 5.0


def test_status_stale_when_all_resets_expired(tmp_path):
    now = 1_000_000.0
    p = tmp_path / "s.json"
    _write(p, {
        "five_hour": {str(int(now - 100_000)): {"used": 40, "observed_at": now - 90_000}},
        "seven_day": {str(int(now - 200_000)): {"used": 12, "observed_at": now - 90_000}},
    })
    status, age = predict.quota_cache_status(now=now, path=p)
    assert status == "stale"
    assert age == 90_000.0


def test_status_fresh_if_any_window_still_plausible(tmp_path):
    now = 1_000_000.0
    p = tmp_path / "s.json"
    _write(p, {
        "five_hour": {str(int(now - 100_000)): {"used": 40}},   # expired
        "seven_day": {str(int(now + 3600)): {"used": 12}},      # still valid
    })
    assert predict.quota_cache_status(now=now, path=p)[0] == "fresh"


def test_status_never_raises_on_garbage(tmp_path):
    p = tmp_path / "s.json"
    p.write_text("{not json", encoding="utf-8")
    assert predict.quota_cache_status(path=p) == ("empty", None)


# --- render ---

def _waiting(quota_stale):
    return progress.format_status_line(
        msgs_pct=None, tkns_pct=None, reset_time="--", model="Opus 4.8",
        weekly_pct=None, ctx_pct=12, use_color=False, quota_stale=quota_stale)


def test_stale_render_shows_hint_not_blank_bars():
    out = _waiting(quota_stale=True)
    assert "stale" in out
    assert "restart" in out
    assert "Opus 4.8" in out
    assert "5h[" not in out and "7d[" not in out   # blank bars replaced


def test_normal_waiting_still_shows_placeholder_bars():
    out = _waiting(quota_stale=False)
    assert "5h[" in out
    assert "--%" in out
    assert "stale" not in out


def test_stale_hint_suppressed_once_real_pct_arrives():
    # A real reading present → never the stale hint, even if the flag is set.
    out = progress.format_status_line(
        msgs_pct=42, tkns_pct=None, reset_time="1h", model="Opus 4.8",
        weekly_pct=18, ctx_pct=12, use_color=False, quota_stale=True)
    assert "stale" not in out
    assert "5h[" in out
