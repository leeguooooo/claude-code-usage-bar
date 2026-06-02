# tests/test_predict.py
from claude_statusbar.predict import format_eta, burn_rate, time_to_limit


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
