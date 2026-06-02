# tests/test_predict.py
from claude_statusbar.predict import format_eta, burn_rate, time_to_limit
from claude_statusbar.predict import _MAX_SAMPLES


def test_format_eta_seconds():
    assert format_eta(30) == "~30s"

def test_format_eta_minutes_no_seconds():
    assert format_eta(40 * 60) == "~40m"
    assert format_eta(8 * 60 + 59) == "~8m"   # floor to minutes in the <1h band

def test_format_eta_hours():
    assert format_eta(2 * 3600 + 10 * 60) == "~2h10m"

def test_burn_rate_two_samples():
    # 10% over 100s → 0.1 %/s
    assert abs(burn_rate([(1000.0, 20.0), (1100.0, 30.0)], now=1100.0, lookback_s=300) - 0.1) < 1e-9

def test_burn_rate_excludes_old_samples():
    # only the last two are within lookback=120s of now=1200
    samples = [(0.0, 5.0), (1090.0, 20.0), (1190.0, 26.0)]
    assert abs(burn_rate(samples, now=1200.0, lookback_s=120) - (6.0 / 100.0)) < 1e-9

def test_burn_rate_insufficient_samples_is_none():
    assert burn_rate([(1000.0, 20.0)], now=1000.0, lookback_s=300) is None
    assert burn_rate([], now=1000.0, lookback_s=300) is None

def test_burn_rate_non_increasing_is_none():
    assert burn_rate([(1000.0, 30.0), (1100.0, 30.0)], now=1100.0, lookback_s=300) is None  # plateau
    assert burn_rate([(1000.0, 30.0), (1100.0, 20.0)], now=1100.0, lookback_s=300) is None  # dipped (rolling)

def test_burn_rate_zero_dt_is_none():
    assert burn_rate([(1000.0, 20.0), (1000.0, 30.0)], now=1000.0, lookback_s=300) is None

def test_time_to_limit():
    assert abs(time_to_limit(60.0, 0.1) - 400.0) < 1e-9   # (100-60)/0.1

def test_time_to_limit_none_rate():
    assert time_to_limit(60.0, None) is None
    assert time_to_limit(60.0, 0.0) is None

def test_time_to_limit_already_full():
    assert time_to_limit(100.0, 0.1) is None


# append to tests/test_predict.py
from claude_statusbar.predict import (
    load_history, save_history, record_sample, _HISTORY_PATH,
)


def test_record_appends_on_pct_change():
    hist = {}
    hist = record_sample(hist, "five_hour", 20.0, now=1000.0)
    hist = record_sample(hist, "five_hour", 30.0, now=1100.0)
    assert hist["five_hour"] == [[1000.0, 20.0], [1100.0, 30.0]]

def test_record_dedups_unchanged_pct():
    hist = record_sample({}, "five_hour", 20.0, now=1000.0)
    hist = record_sample(hist, "five_hour", 20.0, now=1100.0)  # same pct → skip
    assert hist["five_hour"] == [[1000.0, 20.0]]

def test_record_prunes_to_max_samples():
    hist = {}
    for i in range(_MAX_SAMPLES + 50):
        hist = record_sample(hist, "five_hour", float(i), now=float(i))  # each pct differs
    assert len(hist["five_hour"]) == _MAX_SAMPLES
    assert hist["five_hour"][-1] == [float(_MAX_SAMPLES + 49), float(_MAX_SAMPLES + 49)]

def test_load_missing_file_is_empty(tmp_path):
    assert load_history(tmp_path / "nope.json") == {}

def test_load_corrupt_file_is_empty(tmp_path):
    p = tmp_path / "h.json"
    p.write_text("not json{", encoding="utf-8")
    assert load_history(p) == {}

def test_save_then_load_roundtrip(tmp_path):
    p = tmp_path / "h.json"
    hist = {"five_hour": [[1.0, 2.0]], "seven_day": []}
    save_history(hist, p)
    assert load_history(p) == hist


# append to tests/test_predict.py
from claude_statusbar.predict import forecast_chip, forecast


def _hist(window, samples):
    return {window: [[t, p] for (t, p) in samples]}

def test_forecast_chip_at_risk():
    # 60%→90% over 300s = 0.1%/s; ttl=(100-90)/0.1=100s; reset is 9999s away → at risk
    hist = _hist("five_hour", [(1000.0, 60.0), (1300.0, 90.0)])
    chip = forecast_chip(hist, "five_hour", used_pct=90.0,
                         resets_at=1300.0 + 9999, now=1300.0)
    assert chip == "~1m"   # 100s → "~1m" (floored)

def test_forecast_chip_safe_when_reset_first():
    # ttl huge vs reset soon → no chip
    hist = _hist("five_hour", [(1000.0, 10.0), (1300.0, 11.0)])  # ~0.0033%/s
    chip = forecast_chip(hist, "five_hour", used_pct=11.0,
                         resets_at=1300.0 + 60, now=1300.0)  # resets in 60s
    assert chip is None

def test_forecast_chip_none_without_resets_at():
    hist = _hist("five_hour", [(1000.0, 60.0), (1300.0, 90.0)])
    assert forecast_chip(hist, "five_hour", 90.0, resets_at=None, now=1300.0) is None

def test_forecast_chip_none_insufficient_samples():
    hist = _hist("five_hour", [(1300.0, 90.0)])
    assert forecast_chip(hist, "five_hour", 90.0, resets_at=1e12, now=1300.0) is None

def test_forecast_records_and_returns_both(tmp_path, monkeypatch):
    import claude_statusbar.predict as predict
    monkeypatch.setattr(predict, "_HISTORY_PATH", tmp_path / "h.json")
    # First call seeds the history (one sample each) → no chips yet.
    c5, c7 = forecast(used_5h=50.0, resets_5h=1e12, used_7d=10.0,
                      resets_7d=1e12, now=1000.0)
    assert c5 is None and c7 is None
    # Persisted.
    assert (tmp_path / "h.json").exists()


# --- Minimum observation span: don't extrapolate a startup/transient burst ---
# Regression for the dogfood bug: 7d at 7% with a 6-day reset showed "~20m"
# because a ~60s burst (6%→7%) was extrapolated linearly to the 100% cap.
def test_burn_rate_rejects_short_observation_span():
    # 1% over 60s is a real slope, but 60s of data must not feed a multi-hour
    # forecast. With a 300s floor it's rejected; with no floor it still computes
    # (anchors that the ONLY change is the new guard).
    samples = [[1000.0, 6.0], [1060.0, 7.0]]
    assert burn_rate(samples, now=1060.0, lookback_s=1800, min_span_s=300) is None
    assert burn_rate(samples, now=1060.0, lookback_s=1800, min_span_s=0) is not None

def test_burn_rate_accepts_sufficient_span():
    # 2% over 600s clears a 300s floor → 2/600 %/s.
    samples = [[1000.0, 6.0], [1600.0, 8.0]]
    r = burn_rate(samples, now=1600.0, lookback_s=1800, min_span_s=300)
    assert r is not None and abs(r - (2.0 / 600.0)) < 1e-9

def test_forecast_chip_suppresses_startup_transient():
    # The exact reported scenario: 7d at 7%, resets in 6 days, only a 60s burst.
    now = 1_000_000.0
    hist = _hist("seven_day", [(now - 60, 6.0), (now, 7.0)])
    assert forecast_chip(hist, "seven_day", 7.0, resets_at=now + 6 * 86400, now=now) is None

def test_forecast_chip_fires_on_sustained_7d_burn():
    # A genuine sustained 7d burn over a real span still warns.
    now = 1_000_000.0
    hist = _hist("seven_day", [(now - 1800, 10.0), (now, 40.0)])  # 30% / 30min
    chip = forecast_chip(hist, "seven_day", 40.0, resets_at=now + 6 * 86400, now=now)
    assert chip is not None and chip.startswith("~")


# --- Recording throttle: bound sample density so the series spans real time ---
# Regression: in daemon mode every active session wrote the account-global store
# each tick, packing 200 samples into <1 min → span < min-span → chip stuck on
# `~--`. A global time-throttle records at most one sample per gap.
def test_record_sample_throttles_within_gap():
    h = {}
    record_sample(h, "five_hour", 5.0, now=1000.0, min_gap_s=30)
    record_sample(h, "five_hour", 6.0, now=1010.0, min_gap_s=30)  # +10s, changed → throttled
    record_sample(h, "five_hour", 7.0, now=1040.0, min_gap_s=30)  # +40s → recorded
    assert h["five_hour"] == [[1000.0, 5.0], [1040.0, 7.0]]

def test_record_sample_no_throttle_by_default():
    h = {}
    record_sample(h, "five_hour", 5.0, now=1000.0)
    record_sample(h, "five_hour", 6.0, now=1001.0)  # default gap 0 → both land
    assert len(h["five_hour"]) == 2

def test_forecast_throttles_rapid_multiwriter_calls(tmp_path, monkeypatch):
    import claude_statusbar.predict as predict
    monkeypatch.setattr(predict, "_HISTORY_PATH", tmp_path / "h.json")
    predict.forecast(5.0, 1e12, 1.0, 1e12, now=1000.0)
    predict.forecast(6.0, 1e12, 2.0, 1e12, now=1005.0)  # 5s later (another session) → throttled
    h = predict.load_history()
    assert len(h["five_hour"]) == 1 and len(h["seven_day"]) == 1


# --- Debug always-show: a temporary validation toggle (forecast_debug) ---
# Normally the chip is silent unless at-risk; debug mode surfaces the estimate
# continuously so the burn-rate model can be eyeballed against real usage.
def test_forecast_chip_debug_shows_safe_estimate():
    now = 1_000_000.0
    # 0.2% over 30min → ttl ~230h, far beyond the 6-day reset → safe (None normally).
    hist = _hist("seven_day", [(now - 1800, 6.0), (now, 6.2)])
    assert forecast_chip(hist, "seven_day", 6.2, now + 6 * 86400, now) is None
    chip = forecast_chip(hist, "seven_day", 6.2, now + 6 * 86400, now, debug=True)
    assert chip is not None and chip.startswith("~") and chip != "~--"

def test_forecast_chip_debug_placeholder_while_warming():
    now = 1_000_000.0
    hist = _hist("seven_day", [(now - 60, 6.0), (now, 7.0)])  # 60s span < min → no rate
    assert forecast_chip(hist, "seven_day", 7.0, now + 6 * 86400, now) is None
    assert forecast_chip(hist, "seven_day", 7.0, now + 6 * 86400, now, debug=True) == "~--"

def test_forecast_debug_orchestrator_always_returns_chips(tmp_path, monkeypatch):
    import claude_statusbar.predict as predict
    monkeypatch.setattr(predict, "_HISTORY_PATH", tmp_path / "h.json")
    # First call seeds one sample each → warming → placeholders (not None).
    c5, c7 = predict.forecast(50.0, 1e12, 10.0, 1e12, now=1000.0, debug=True)
    assert c5 == "~--" and c7 == "~--"


# --- Fail-safe on a hand-corrupted (structurally-valid-JSON) history series ---
# A malformed element (wrong arity / non-list) must never raise: the contract is
# "odd input → None/skip", enforced at the helper level, not just the orchestrator.
def test_burn_rate_skips_malformed_elements():
    samples = [[1000.0], "garbage", {"t": 1}, [1100.0, 30.0], [1000.0, 20.0]]
    # Only the two well-formed pairs survive → 10% / 100s = 0.1 %/s.
    assert abs(burn_rate(samples, now=1100.0, lookback_s=300) - 0.1) < 1e-9

def test_record_sample_survives_malformed_last_element():
    hist = {"five_hour": [[1000.0], "garbage"]}
    # Must not raise on the dedup peek; appends the new well-formed sample.
    out = record_sample(hist, "five_hour", 42.0, now=1100.0)
    assert out["five_hour"][-1] == [1100.0, 42.0]

def test_forecast_returns_none_pair_on_malformed_history(tmp_path, monkeypatch):
    import claude_statusbar.predict as predict
    monkeypatch.setattr(predict, "_HISTORY_PATH", tmp_path / "h.json")
    (tmp_path / "h.json").write_text(
        '{"five_hour": [[1.0], "x"], "seven_day": "nope"}',
        encoding="utf-8",
    )
    # Malformed series elements (wrong arity / non-list) must be skipped, never
    # raise. After seeding one fresh sample each window still has <2 well-formed
    # pairs, so the orchestrator degrades to (None, None) instead of crashing.
    assert forecast(used_5h=90.0, resets_5h=1e12, used_7d=10.0,
                    resets_7d=1e12, now=1000.0) == (None, None)
