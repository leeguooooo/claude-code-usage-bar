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
    pf, ttl = project_window(90.0, time_to_reset=3600, window_len=W5)
    assert abs(pf - 112.5) < 1e-6
    assert abs(ttl - 1600.0) < 1e-6

def test_project_window_safe_pace():
    pf, ttl = project_window(8.0, time_to_reset=11580, window_len=W5)
    assert 22 <= pf <= 23
    assert ttl > 11580

def test_project_window_before_window_start_is_none():
    assert project_window(10.0, time_to_reset=W5 + 100, window_len=W5) is None

def test_project_window_no_usage_or_capped_is_none():
    assert project_window(0.0, time_to_reset=3600, window_len=W5) is None
    assert project_window(100.0, time_to_reset=3600, window_len=W5) is None
    assert project_window(5.0, time_to_reset=0, window_len=W5) is None

def test_project_window_bad_input_is_none():
    assert project_window("x", time_to_reset=3600, window_len=W5) is None
    assert project_window(None, time_to_reset=3600, window_len=W5) is None


# --- forecast_chip: ETA-only (show_forecast on) ---
def test_forecast_chip_safe_returns_none():
    now = 1000.0
    assert forecast_chip("five_hour", 8.0, resets_at=now + 11580, now=now) is None

def test_forecast_chip_at_risk_shows_eta():
    now = 1000.0
    # 90% with 1h left → projected 112.5% ≥ 100 → ETA ~26m.
    assert forecast_chip("five_hour", 90.0, resets_at=now + 3600, now=now) == "~26m"

def test_forecast_chip_too_early_is_placeholder():
    now = 1000.0
    ttr = W5 - 300   # only 5 min elapsed (< MIN_ELAPSED 10m)
    assert forecast_chip("five_hour", 5.0, resets_at=now + ttr, now=now) is None

def test_forecast_chip_missing_resets_at_is_placeholder():
    assert forecast_chip("five_hour", 90.0, resets_at=None, now=1000.0) is None

def test_forecast_chip_unknown_window_is_placeholder():
    assert forecast_chip("bogus", 90.0, resets_at=1e12, now=1000.0) is None

def test_forecast_chip_seven_day_uses_week_length():
    now = 1000.0
    assert forecast_chip("seven_day", 8.0, resets_at=now + 536400, now=now) is None
    # Heavy 7d pace (90%, 1 day left → projected ~105%, but the cap is ~16h away)
    # → not imminent enough for a warning chip.
    assert forecast_chip("seven_day", 90.0, resets_at=now + 86400, now=now) is None

def test_forecast_chip_eta_only_when_imminent():
    now = 1000.0
    # 5h projected ~108% but the cap is ~3.2h away (ttl > 1h) → no ETA yet.
    assert forecast_chip("five_hour", 30.0, resets_at=now + 13000, now=now) is None
    # 5h projected 112% with the cap ~26 min away (ttl ≤ 1h) → the countdown.
    assert forecast_chip("five_hour", 90.0, resets_at=now + 3600, now=now) == "~26m"


# --- forecast orchestrator (reconcile isolated to tmp by conftest autouse) ---
def test_forecast_returns_pair():
    now = 1000.0
    c5, c7 = forecast(90.0, now + 3600, 8.0, now + 536400, now)
    assert c5 == "~26m" and c7 is None

def test_forecast_safe_returns_none_pair():
    now = 1000.0
    c5, c7 = forecast(8.0, now + 11580, 8.0, now + 536400, now)
    assert c5 is None and c7 is None

def test_forecast_never_raises_on_garbage():
    assert forecast(None, None, None, None, now=1000.0) == (None, None)
    c5, c7 = forecast("x", "y", object(), [], now=1000.0)
    assert c5 is None and c7 is None


# --- reconcile_account: all windows converge to the freshest account reading ---
def test_reconcile_keeps_higher_used_within_window(tmp_path):
    p = tmp_path / "latest.json"
    reconcile_account(10.0, 5000, 8.0, 9000, path=p, now=0.0)
    u5, r5, u7, r7 = reconcile_account(5.0, 5000, 3.0, 9000, path=p, now=0.0)
    assert (u5, r5, u7, r7) == (10.0, 5000.0, 8.0, 9000.0)

def test_reconcile_takes_higher_used_when_fresher(tmp_path):
    p = tmp_path / "latest.json"
    reconcile_account(10.0, 5000, 8.0, 9000, path=p, now=0.0)
    reconcile_account(12.0, 5000, 9.0, 9000, path=p, now=0.0)
    u5, _, _, _ = reconcile_account(11.0, 5000, 8.5, 9000, path=p, now=0.0)
    assert u5 == 12.0

def test_reconcile_new_window_resets(tmp_path):
    p = tmp_path / "latest.json"
    reconcile_account(90.0, 5000, 50.0, 9000, path=p, now=0.0)
    u5, r5, _, _ = reconcile_account(3.0, 5000 + W5, 50.0, 9000, path=p, now=0.0)
    assert u5 == 3.0 and r5 == 5000 + W5

def test_reconcile_missing_file_returns_inputs(tmp_path):
    p = tmp_path / "nope.json"
    assert reconcile_account(7.0, 5000, 4.0, 9000, path=p, now=0.0) == (7.0, 5000.0, 4.0, 9000.0)

def test_forecast_uses_reconciled_reading(tmp_path, monkeypatch):
    import claude_statusbar.predict as predict
    monkeypatch.setattr(predict, "_LATEST_PATH", tmp_path / "latest.json")
    now = 1000.0
    # Active window seeds used=90 (5h, 1h to reset → at-risk).
    forecast(90.0, now + 3600, 8.0, now + 536400, now)
    # A stale window with used=5 must still see the at-risk ETA (reconciled to 90).
    c5, _ = forecast(5.0, now + 3600, 8.0, now + 536400, now)
    assert c5 == "~26m"


def test_reconcile_rejects_far_future_reset(tmp_path):
    # A bogus far-future resets_at must NOT overwrite a plausible stored reading
    # (regression: a 1e10 value used to poison the monotonic merge forever).
    p = tmp_path / "latest.json"
    now = 1000.0
    reconcile_account(10.0, now + 3000, 8.0, now + 9000, path=p, now=now)
    u5, r5, u7, r7 = reconcile_account(99.0, now + 10**9, 99.0, now + 10**9, path=p, now=now)
    assert (u5, r5) == (10.0, now + 3000) and (u7, r7) == (8.0, now + 9000)


def test_reconcile_accepts_official_rebaseline_after_grace(tmp_path):
    # Anthropic can revise used_percentage DOWN mid-window (weekly limit raised
    # → same resets_at, lower pct; observed live 2026-06-10: seven_day 19% → 3%).
    # Once the old high reading stops being confirmed for DOWNGRADE_GRACE_S,
    # the lower official reading must win — not stick until window rollover.
    from claude_statusbar.predict import DOWNGRADE_GRACE_S
    p = tmp_path / "latest.json"
    reconcile_account(15.0, 5000, 19.0, 9000, path=p, now=0.0)
    later = DOWNGRADE_GRACE_S + 1
    _, _, u7, r7 = reconcile_account(15.0, 5000, 3.0, 9000, path=p, now=later)
    assert (u7, r7) == (3.0, 9000.0)

def test_reconcile_rejects_downgrade_within_grace(tmp_path):
    # Within the grace period a lower same-reset reading is still treated as a
    # stale session replay — the higher stored reading wins.
    p = tmp_path / "latest.json"
    reconcile_account(15.0, 5000, 19.0, 9000, path=p, now=0.0)
    _, _, u7, _ = reconcile_account(15.0, 5000, 3.0, 9000, path=p, now=30.0)
    assert u7 == 19.0

def test_reconcile_confirmation_keeps_high_reading_alive(tmp_path):
    # A session still seeing the high value re-confirms it each render, so the
    # grace clock restarts — a stale lower replay must not take over while any
    # live session agrees with the stored reading.
    from claude_statusbar.predict import DOWNGRADE_GRACE_S
    p = tmp_path / "latest.json"
    reconcile_account(15.0, 5000, 19.0, 9000, path=p, now=0.0)
    confirm_at = DOWNGRADE_GRACE_S - 20
    reconcile_account(15.0, 5000, 19.0, 9000, path=p, now=confirm_at)  # confirm
    _, _, u7, _ = reconcile_account(15.0, 5000, 3.0, 9000, path=p,
                                    now=confirm_at + DOWNGRADE_GRACE_S - 1)
    assert u7 == 19.0
    _, _, u7, _ = reconcile_account(15.0, 5000, 3.0, 9000, path=p,
                                    now=confirm_at + DOWNGRADE_GRACE_S + 1)
    assert u7 == 3.0

def test_reconcile_legacy_store_without_observed_at_accepts_downgrade(tmp_path):
    # Pre-3.13.3 stores have no observed_at — treat them as unconfirmed so a
    # live official reading immediately replaces a stuck pre-upgrade value.
    import json
    p = tmp_path / "latest.json"
    p.write_text(json.dumps({
        "five_hour": {"used": 15.0, "resets_at": 5000.0},
        "seven_day": {"used": 19.0, "resets_at": 9000.0},
    }))
    _, _, u7, r7 = reconcile_account(15.0, 5000, 3.0, 9000, path=p, now=0.0)
    assert (u7, r7) == (3.0, 9000.0)


def test_reconcile_replaces_poisoned_stored_reset(tmp_path):
    import json
    p = tmp_path / "latest.json"
    now = 1000.0
    p.write_text(json.dumps({
        "five_hour": {"used": 12.0, "resets_at": 9999999999.0},
        "seven_day": {"used": 30.0, "resets_at": 9999999999.0},
    }))
    u5, r5, u7, r7 = reconcile_account(5.0, now + 3000, 4.0, now + 9000, path=p, now=now)
    assert (u5, r5, u7, r7) == (5.0, now + 3000, 4.0, now + 9000)
