import json
from datetime import datetime, timezone

from claude_statusbar import predict


def _ts(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc).timestamp()


def test_load_projection_store_missing_is_empty(tmp_path):
    store = predict.load_projection_store(tmp_path / "missing.json")
    assert store["version"] == 1
    assert store["five_hour"] == []
    assert store["seven_day"] == []
    assert store["display"] == {}
    assert store["snapshots"] == []
    assert store["closed_windows"] == []


def test_record_projection_sample_accepts_lower_newer_same_reset(tmp_path):
    p = tmp_path / "projection.json"
    store = predict.load_projection_store(p)
    store = predict.record_projection_sample(
        store, "five_hour", used_pct=20.0, resets_at=5000.0,
        observed_at=1000.0, session_id="a"
    )
    store = predict.record_projection_sample(
        store, "five_hour", used_pct=18.0, resets_at=5000.0,
        observed_at=1010.0, session_id="b"
    )
    assert [s["used_pct"] for s in store["five_hour"]] == [20.0, 18.0]


def test_record_projection_sample_prunes_bounded_history(monkeypatch):
    monkeypatch.setattr(predict, "MAX_PROJECTION_SAMPLES", 3)
    store = predict.empty_projection_store()
    for i in range(5):
        store = predict.record_projection_sample(
            store, "seven_day", used_pct=float(i), resets_at=9000.0,
            observed_at=1000.0 + i, session_id="s"
        )
    assert [s["used_pct"] for s in store["seven_day"]] == [2.0, 3.0, 4.0]


def test_save_projection_store_atomic_roundtrip(tmp_path):
    p = tmp_path / "projection.json"
    store = predict.empty_projection_store()
    store = predict.record_projection_sample(
        store, "five_hour", used_pct=7.0, resets_at=5000.0,
        observed_at=1000.0, session_id="s"
    )
    predict.save_projection_store(store, p)
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert raw["five_hour"][0]["used_pct"] == 7.0


def test_bucket_for_time_distinguishes_weekday_work_weekend_and_night():
    assert predict.bucket_for_time(_ts(2026, 6, 1, 1)) == "weekday_work_hours"      # Mon 10:00 JST
    assert predict.bucket_for_time(_ts(2026, 6, 1, 10)) == "weekday_non_work_hours" # Mon 19:00 JST
    assert predict.bucket_for_time(_ts(2026, 6, 1, 18)) == "night"                  # Tue 03:00 JST
    assert predict.bucket_for_time(_ts(2026, 6, 6, 3)) == "weekend"                # Sat 12:00 JST


def test_learned_bucket_rates_from_positive_deltas():
    samples = [
        {"observed_at": _ts(2026, 6, 1, 1), "used_pct": 10.0, "resets_at": 1780927200.0, "session_id": "s"},
        {"observed_at": _ts(2026, 6, 1, 2), "used_pct": 12.0, "resets_at": 1780927200.0, "session_id": "s"},
    ]
    rates = predict.learn_bucket_rates(samples)
    assert rates["weekday_work_hours"]["samples"] == 1
    assert abs(rates["weekday_work_hours"]["rate_per_hour"] - 2.0) < 1e-9


def test_expected_bucket_rate_blends_prior_and_learned_by_coverage():
    learned = {"rate_per_hour": 4.0, "samples": 1}
    low = predict.expected_bucket_rate("weekday_work_hours", learned)
    learned_more = {"rate_per_hour": 4.0, "samples": 20}
    high = predict.expected_bucket_rate("weekday_work_hours", learned_more)
    prior = predict.DEFAULT_BUCKET_PRIORS["weekday_work_hours"]
    assert prior < low < high < 4.01


def test_integrate_future_buckets_uses_future_schedule():
    start = _ts(2026, 6, 1, 1)  # Monday 10:00 Tokyo.
    end = start + 2 * 3600
    usage = predict.integrate_future_buckets(start, end, {})
    expected = 2 * predict.DEFAULT_BUCKET_PRIORS["weekday_work_hours"]
    assert abs(usage - expected) < 1e-6


def test_project_5h_blends_recent_window_and_bucket():
    now = 10_000.0
    reset = now + 3600.0
    samples = [
        {"observed_at": now - 3600, "used_pct": 20.0, "resets_at": reset, "session_id": "s"},
        {"observed_at": now, "used_pct": 30.0, "resets_at": reset, "session_id": "s"},
    ]
    projected = predict.project_5h(30.0, reset, now, samples)
    assert projected > 30.0
    assert projected <= 100.0


def test_project_7d_does_not_extrapolate_first_18h_to_full_week():
    now = 10_000.0
    reset = now + (6 * 86400 + 5 * 3600)
    current = 10.0
    naive = current * predict.WINDOW_LEN_S["seven_day"] / (predict.WINDOW_LEN_S["seven_day"] - (reset - now))
    projected = predict.project_7d(current, reset, now, [])
    assert projected < naive
    assert projected >= current


def test_smooth_projection_uses_wall_clock_dt_not_render_count():
    prev = {"projected_pct": 50.0, "updated_at": 1000.0}
    once = predict.smooth_projection("seven_day", raw=80.0, current_used=10.0,
                                     observed_at=1060.0, previous=prev)
    many = prev
    for _ in range(60):
        many = predict.smooth_projection("seven_day", raw=80.0, current_used=10.0,
                                         observed_at=1060.0, previous=many)
    assert once == many


def test_close_window_records_actual_final_pct():
    store = predict.empty_projection_store()
    store = predict.record_projection_sample(store, "five_hour", 20, 5000, 1000, "s")
    store = predict.record_projection_sample(store, "five_hour", 25, 6000, 2000, "s")
    predict.close_changed_windows(store, "five_hour")
    assert store["closed_windows"][0]["actual_final_pct"] == 20.0


def test_projection_returns_arrow_strings_and_persists_store(tmp_path, monkeypatch):
    monkeypatch.setattr(predict, "_PROJECTION_PATH", tmp_path / "projection.json")
    now = 1000.0
    p5, p7 = predict.projection(
        used_5h=10.0, resets_5h=now + 3600,
        used_7d=8.0, resets_7d=now + 6 * 86400,
        now=now, session_id="s"
    )
    assert p5.startswith("→")
    assert p5.endswith("%")
    assert p7.startswith("→")
    assert (tmp_path / "projection.json").exists()
