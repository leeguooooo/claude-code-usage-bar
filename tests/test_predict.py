# tests/test_predict.py
from claude_statusbar.predict import (
    format_eta, project_window, forecast_chip, forecast, reconcile_account,
    WINDOW_LEN_S, MIN_ELAPSED_S, DEBUG_PLACEHOLDER,
)

W5 = WINDOW_LEN_S["five_hour"]    # 18000
W7 = WINDOW_LEN_S["seven_day"]    # 604800


# --- format_eta ---
def test_format_eta_seconds():
    assert format_eta(30) == "~30s"

def test_format_eta_minutes_floor():
    assert format_eta(40 * 60) == "~40m"
    assert format_eta(8 * 60 + 59) == "~8m"

def test_format_eta_hours():
    assert format_eta(2 * 3600 + 10 * 60) == "~2h10m"


# --- project_window: average pace over the elapsed window ---
def test_project_window_basic():
    # used 90% with 1h left on the 5h window → window 4h elapsed.
    # avg = 90/14400 %/s; projected = 90 + avg*3600 = 112.5; ttl = 10/avg = 1600s.
    pf, ttl = project_window(90.0, time_to_reset=3600, window_len=W5)
    assert abs(pf - 112.5) < 1e-6
    assert abs(ttl - 1600.0) < 1e-6

def test_project_window_safe_pace():
    # 8% with 3h13m left → ends ~22%, nowhere near the cap.
    pf, ttl = project_window(8.0, time_to_reset=11580, window_len=W5)
    assert 22 <= pf <= 23
    assert ttl > 11580           # would hit 100 long after the reset

def test_project_window_before_window_start_is_none():
    # reset further out than a whole window → elapsed ≤ 0 → can't project.
    assert project_window(10.0, time_to_reset=W5 + 100, window_len=W5) is None

def test_project_window_no_usage_or_capped_is_none():
    assert project_window(0.0, time_to_reset=3600, window_len=W5) is None
    assert project_window(100.0, time_to_reset=3600, window_len=W5) is None
    assert project_window(5.0, time_to_reset=0, window_len=W5) is None

def test_project_window_bad_input_is_none():
    assert project_window("x", time_to_reset=3600, window_len=W5) is None
    assert project_window(None, time_to_reset=3600, window_len=W5) is None


# --- forecast_chip: production = at-risk ETA only ---
def test_forecast_chip_at_risk_returns_eta():
    now = 1000.0
    # 90% with 1h left → projected 112.5% ≥ 100 → ETA ~26m.
    chip = forecast_chip("five_hour", 90.0, resets_at=now + 3600, now=now)
    assert chip == "~26m"

def test_forecast_chip_safe_returns_none():
    now = 1000.0
    # 8% with 3h13m left → projected ~22% → no chip in production.
    assert forecast_chip("five_hour", 8.0, resets_at=now + 11580, now=now) is None

def test_forecast_chip_too_early_returns_none():
    now = 1000.0
    # 5h window, only 5 min elapsed (< MIN_ELAPSED 10m) → defer.
    ttr = W5 - 300
    assert forecast_chip("five_hour", 5.0, resets_at=now + ttr, now=now) is None

def test_forecast_chip_missing_resets_at_returns_none():
    assert forecast_chip("five_hour", 90.0, resets_at=None, now=1000.0) is None

def test_forecast_chip_unknown_window_returns_none():
    assert forecast_chip("bogus", 90.0, resets_at=1e12, now=1000.0) is None

def test_forecast_chip_seven_day_uses_week_length():
    now = 1000.0
    # 8% with 6d05h left → projected ~71% → safe → None.
    assert forecast_chip("seven_day", 8.0, resets_at=now + 536400, now=now) is None
    # But a heavy 7d pace (60% with 1 day left → window 6 days elapsed):
    # avg = 60/(6d) ; projected = 60 + avg*1d = 70 → still safe.
    # Push it: 90% with 1 day left → projected = 90 + (90/6d)*1d = 105 → at-risk.
    chip = forecast_chip("seven_day", 90.0, resets_at=now + 86400, now=now)
    assert chip is not None and chip.startswith("~")


# --- forecast_chip: debug always-show projected end-of-window % ---
def test_forecast_chip_debug_shows_projected_pct():
    now = 1000.0
    chip = forecast_chip("five_hour", 8.0, resets_at=now + 11580, now=now, debug=True)
    assert chip == "→22%"

def test_forecast_chip_debug_seven_day_projected_pct():
    now = 1000.0
    chip = forecast_chip("seven_day", 8.0, resets_at=now + 536400, now=now, debug=True)
    assert chip == "→71%"

def test_forecast_chip_debug_at_risk_still_eta():
    now = 1000.0
    # At-risk in debug still shows the ETA (the real signal), not a projection.
    assert forecast_chip("five_hour", 90.0, resets_at=now + 3600, now=now, debug=True) == "~26m"

def test_forecast_chip_debug_placeholder_when_too_early():
    now = 1000.0
    ttr = W5 - 300   # 5 min elapsed < MIN_ELAPSED
    assert forecast_chip("five_hour", 5.0, resets_at=now + ttr, now=now, debug=True) == DEBUG_PLACEHOLDER

def test_forecast_chip_debug_placeholder_without_resets_at():
    assert forecast_chip("five_hour", 50.0, resets_at=None, now=1000.0, debug=True) == DEBUG_PLACEHOLDER


# --- forecast orchestrator ---
def test_forecast_returns_pair():
    now = 1000.0
    c5, c7 = forecast(90.0, now + 3600, 8.0, now + 536400, now)
    assert c5 == "~26m" and c7 is None

def test_forecast_debug_returns_projections():
    now = 1000.0
    c5, c7 = forecast(8.0, now + 11580, 8.0, now + 536400, now, debug=True)
    assert c5 == "→22%" and c7 == "→71%"

def test_forecast_never_raises_on_garbage():
    # Any odd input degrades to a (None, None) / placeholder pair, never an error.
    assert forecast(None, None, None, None, now=1000.0) == (None, None)
    c5, c7 = forecast("x", "y", object(), [], now=1000.0, debug=True)
    assert c5 == DEBUG_PLACEHOLDER and c7 == DEBUG_PLACEHOLDER


# --- reconcile_account: all windows converge to the freshest account reading ---
def test_reconcile_keeps_higher_used_within_window(tmp_path):
    p = tmp_path / "latest.json"
    # Window A reports used=10 first.
    reconcile_account(10.0, 5000, 8.0, 9000, path=p)
    # Window B's stale stdin says used=5 (same reset) → must read back the 10.
    u5, r5, u7, r7 = reconcile_account(5.0, 5000, 3.0, 9000, path=p)
    assert (u5, r5, u7, r7) == (10.0, 5000.0, 8.0, 9000.0)

def test_reconcile_takes_higher_used_when_fresher(tmp_path):
    p = tmp_path / "latest.json"
    reconcile_account(10.0, 5000, 8.0, 9000, path=p)
    # A newer reading with higher used wins and is persisted for the next reader.
    reconcile_account(12.0, 5000, 9.0, 9000, path=p)
    u5, r5, _, _ = reconcile_account(11.0, 5000, 8.5, 9000, path=p)
    assert u5 == 12.0

def test_reconcile_new_window_resets(tmp_path):
    p = tmp_path / "latest.json"
    reconcile_account(90.0, 5000, 50.0, 9000, path=p)
    # 5h reset moved later (new window) with low used → adopt the new window.
    u5, r5, _, _ = reconcile_account(3.0, 5000 + WINDOW_LEN_S["five_hour"], 50.0, 9000, path=p)
    assert u5 == 3.0 and r5 == 5000 + WINDOW_LEN_S["five_hour"]

def test_reconcile_missing_file_returns_inputs(tmp_path):
    p = tmp_path / "nope.json"
    assert reconcile_account(7.0, 5000, 4.0, 9000, path=p) == (7.0, 5000.0, 4.0, 9000.0)

def test_forecast_uses_reconciled_reading(tmp_path, monkeypatch):
    import claude_statusbar.predict as predict
    monkeypatch.setattr(predict, "_LATEST_PATH", tmp_path / "latest.json")
    now = 1000.0
    # Active window seeds used=90 (5h, 1h to reset → at-risk).
    forecast(90.0, now + 3600, 8.0, now + 536400, now)
    # A stale window with used=5 must still see the at-risk ETA (reconciled to 90).
    c5, _ = forecast(5.0, now + 3600, 8.0, now + 536400, now)
    assert c5 == "~26m"
