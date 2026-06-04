import json
import os
import time
from datetime import datetime, timezone

import pytest

from claude_statusbar import predict


def _ts(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc).timestamp()


@pytest.fixture
def use_tz(monkeypatch):
    old_tz = os.environ.get("TZ")

    def apply(name):
        monkeypatch.setenv("TZ", name)
        if hasattr(time, "tzset"):
            time.tzset()

    yield apply

    if old_tz is None:
        monkeypatch.delenv("TZ", raising=False)
    else:
        monkeypatch.setenv("TZ", old_tz)
    if hasattr(time, "tzset"):
        time.tzset()


def test_load_projection_store_missing_is_empty(tmp_path):
    store = predict.load_projection_store(tmp_path / "missing.json")
    assert store["version"] == 1
    assert store["five_hour"] == []
    assert store["seven_day"] == []
    assert store["display"] == {}
    assert store["snapshots"] == []
    assert store["closed_windows"] == []


def test_load_projection_store_compacts_legacy_duplicate_samples(tmp_path):
    p = tmp_path / "projection.json"
    p.write_text(json.dumps({
        "version": 1,
        "five_hour": [
            {"observed_at": 1000.0, "used_pct": 10.0, "resets_at": 5000.0, "session_id": "a"},
            {"observed_at": 1001.0, "used_pct": 10.0, "resets_at": 5000.0, "session_id": "b"},
            {"observed_at": 1002.0, "used_pct": 9.0, "resets_at": 5000.0, "session_id": "stale"},
            {"observed_at": 2000.0, "used_pct": 11.0, "resets_at": 5000.0, "session_id": "a"},
        ],
        "seven_day": [],
        "display": {},
        "snapshots": [],
        "closed_windows": [],
    }), encoding="utf-8")

    store = predict.load_projection_store(p)

    assert [s["used_pct"] for s in store["five_hour"]] == [10.0, 11.0]


def test_record_projection_sample_keeps_one_monotonic_reading_per_pct_step(tmp_path):
    p = tmp_path / "projection.json"
    store = predict.load_projection_store(p)
    store = predict.record_projection_sample(
        store, "five_hour", used_pct=20.0, resets_at=5000.0,
        observed_at=1000.0, session_id="a"
    )
    store = predict.record_projection_sample(
        store, "five_hour", used_pct=20.0, resets_at=5000.0,
        observed_at=1001.0, session_id="b"
    )
    store = predict.record_projection_sample(
        store, "five_hour", used_pct=18.0, resets_at=5000.0,
        observed_at=1010.0, session_id="b"
    )
    store = predict.record_projection_sample(
        store, "five_hour", used_pct=21.0, resets_at=5000.0,
        observed_at=2000.0, session_id="a"
    )
    assert [s["used_pct"] for s in store["five_hour"]] == [20.0, 21.0]


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


def test_bucket_for_time_distinguishes_weekday_work_weekend_and_night(use_tz):
    use_tz("Asia/Tokyo")
    assert predict.bucket_for_time(_ts(2026, 6, 1, 1)) == "weekday_work_hours"      # Mon 10:00 JST
    assert predict.bucket_for_time(_ts(2026, 6, 1, 10)) == "weekday_non_work_hours" # Mon 19:00 JST
    assert predict.bucket_for_time(_ts(2026, 6, 1, 18)) == "night"                  # Tue 03:00 JST
    assert predict.bucket_for_time(_ts(2026, 6, 6, 3)) == "weekend"                # Sat 12:00 JST


def test_bucket_for_time_uses_system_local_timezone(use_tz):
    ts = _ts(2026, 6, 1, 1)  # 01:00 UTC, 10:00 JST.
    use_tz("UTC")
    assert predict.bucket_for_time(ts) == "night"
    use_tz("Asia/Tokyo")
    assert predict.bucket_for_time(ts) == "weekday_work_hours"


def test_learned_bucket_rates_from_positive_deltas(use_tz):
    use_tz("Asia/Tokyo")
    samples = [
        {"observed_at": _ts(2026, 6, 1, 1), "used_pct": 10.0, "resets_at": 1780927200.0, "session_id": "s"},
        {"observed_at": _ts(2026, 6, 1, 2), "used_pct": 12.0, "resets_at": 1780927200.0, "session_id": "s"},
    ]
    rates = predict.learn_bucket_rates(samples)
    assert rates["weekday_work_hours"]["samples"] == 1
    assert abs(rates["weekday_work_hours"]["rate_per_hour"] - 2.0) < 1e-9


def test_learned_bucket_rates_compress_duplicate_plateaus(use_tz):
    use_tz("Asia/Tokyo")
    reset = 1780927200.0
    samples = [
        {"observed_at": _ts(2026, 6, 1, 1, 0), "used_pct": 10.0, "resets_at": reset, "session_id": "a"},
        {"observed_at": _ts(2026, 6, 1, 1, 10), "used_pct": 10.0, "resets_at": reset, "session_id": "b"},
        {"observed_at": _ts(2026, 6, 1, 1, 20), "used_pct": 11.0, "resets_at": reset, "session_id": "a"},
    ]
    rates = predict.learn_bucket_rates(samples)
    assert rates["weekday_work_hours"]["samples"] == 1
    assert abs(rates["weekday_work_hours"]["rate_per_hour"] - 3.0) < 1e-9


def test_learned_bucket_rates_ignore_stale_lower_session_readings(use_tz):
    use_tz("Asia/Tokyo")
    reset = 1780927200.0
    samples = [
        {"observed_at": _ts(2026, 6, 1, 1, 0), "used_pct": 15.0, "resets_at": reset, "session_id": "fresh"},
        {"observed_at": _ts(2026, 6, 1, 1, 10), "used_pct": 14.0, "resets_at": reset, "session_id": "stale"},
        {"observed_at": _ts(2026, 6, 1, 1, 20), "used_pct": 16.0, "resets_at": reset, "session_id": "fresh"},
    ]
    rates = predict.learn_bucket_rates(samples)
    assert rates["weekday_work_hours"]["samples"] == 1
    assert abs(rates["weekday_work_hours"]["rate_per_hour"] - 3.0) < 1e-9


def test_expected_bucket_rate_blends_prior_and_learned_by_coverage():
    learned = {"rate_per_hour": 4.0, "samples": 1}
    low = predict.expected_bucket_rate("weekday_work_hours", learned)
    learned_more = {"rate_per_hour": 4.0, "samples": 20}
    high = predict.expected_bucket_rate("weekday_work_hours", learned_more)
    prior = predict.DEFAULT_BUCKET_PRIORS["weekday_work_hours"]
    assert prior < low < high < 4.01


def test_integrate_future_buckets_uses_future_schedule(use_tz):
    use_tz("Asia/Tokyo")
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


def test_close_window_ignores_reset_bouncing_backwards():
    store = predict.empty_projection_store()
    store["five_hour"] = [
        {"observed_at": 1000.0, "used_pct": 20.0, "resets_at": 5000.0, "session_id": "fresh"},
        {"observed_at": 2000.0, "used_pct": 1.0, "resets_at": 6000.0, "session_id": "fresh"},
        {"observed_at": 2010.0, "used_pct": 20.0, "resets_at": 5000.0, "session_id": "stale"},
    ]
    predict.close_changed_windows(store, "five_hour")
    assert [
        (w["previous_resets_at"], w["actual_final_pct"])
        for w in store["closed_windows"]
    ] == [(5000.0, 20.0)]


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


def test_projection_does_not_smooth_across_reset_boundaries(tmp_path, monkeypatch):
    monkeypatch.setattr(predict, "_PROJECTION_PATH", tmp_path / "projection.json")
    now = _ts(2026, 6, 1, 1)
    old_reset = now + 60
    new_reset = now + 4 * 3600 + 48 * 60
    store = predict.empty_projection_store()
    store["display"] = {
        "five_hour": {
            "projected_pct": 3.0,
            "updated_at": now - 30,
            "resets_at": old_reset,
        }
    }
    predict.save_projection_store(store)

    p5, _ = predict.projection(
        used_5h=1.0, resets_5h=new_reset,
        used_7d=15.0, resets_7d=now + 4 * 86400,
        now=now, session_id="s",
    )

    assert int(p5.lstrip("→").rstrip("%")) > 10


def test_projection_reconciles_stale_session_readings_before_recording(tmp_path, monkeypatch):
    monkeypatch.setattr(predict, "_LATEST_PATH", tmp_path / "latest.json")
    monkeypatch.setattr(predict, "_PROJECTION_PATH", tmp_path / "projection.json")
    now = _ts(2026, 6, 1, 1)
    reset = now + 4 * 3600

    predict.projection(20.0, reset, 15.0, now + 6 * 86400, now, session_id="fresh")
    p5, _ = predict.projection(10.0, reset, 15.0, now + 6 * 86400, now + 10, session_id="stale")

    store = predict.load_projection_store()
    assert [s["used_pct"] for s in store["five_hour"]] == [20.0]
    assert int(p5.lstrip("→").rstrip("%")) >= 20


def test_projection_reuses_recent_account_result_without_store_churn(tmp_path, monkeypatch):
    monkeypatch.setattr(predict, "_LATEST_PATH", tmp_path / "latest.json")
    monkeypatch.setattr(predict, "_PROJECTION_PATH", tmp_path / "projection.json")
    now = _ts(2026, 6, 1, 1)
    reset_5h = now + 4 * 3600
    reset_7d = now + 4 * 86400

    saves = []
    real_save = predict.save_projection_store

    def counting_save(store, path=None):
        saves.append(1)
        real_save(store, path)

    monkeypatch.setattr(predict, "save_projection_store", counting_save)

    first = predict.projection(20.0, reset_5h, 18.0, reset_7d, now, session_id="a")
    second = predict.projection(20.0, reset_5h, 18.0, reset_7d, now + 0.25, session_id="b")
    third = predict.projection(20.0, reset_5h, 18.0, reset_7d, now + 0.50, session_id="c")

    assert second == first
    assert third == first
    assert len(saves) == 1
    store = predict.load_projection_store()
    assert len(store["snapshots"]) == 2


def test_projection_recomputes_after_result_cache_ttl(tmp_path, monkeypatch):
    monkeypatch.setattr(predict, "_LATEST_PATH", tmp_path / "latest.json")
    monkeypatch.setattr(predict, "_PROJECTION_PATH", tmp_path / "projection.json")
    now = _ts(2026, 6, 1, 1)
    reset_5h = now + 4 * 3600
    reset_7d = now + 4 * 86400

    saves = []
    real_save = predict.save_projection_store

    def counting_save(store, path=None):
        saves.append(1)
        real_save(store, path)

    monkeypatch.setattr(predict, "save_projection_store", counting_save)

    predict.projection(20.0, reset_5h, 18.0, reset_7d, now, session_id="a")
    predict.projection(20.0, reset_5h, 18.0, reset_7d, now + 2.0, session_id="b")

    assert len(saves) == 2


def test_projection_recomputes_when_account_reading_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(predict, "_LATEST_PATH", tmp_path / "latest.json")
    monkeypatch.setattr(predict, "_PROJECTION_PATH", tmp_path / "projection.json")
    now = _ts(2026, 6, 1, 1)
    reset_5h = now + 4 * 3600
    reset_7d = now + 4 * 86400

    saves = []
    real_save = predict.save_projection_store

    def counting_save(store, path=None):
        saves.append(1)
        real_save(store, path)

    monkeypatch.setattr(predict, "save_projection_store", counting_save)

    predict.projection(20.0, reset_5h, 18.0, reset_7d, now, session_id="a")
    predict.projection(21.0, reset_5h, 18.0, reset_7d, now + 0.25, session_id="b")

    assert len(saves) == 2
