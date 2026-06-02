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
