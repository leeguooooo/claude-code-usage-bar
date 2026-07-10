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


def test_record_projection_sample_dedups_equal_readings(tmp_path):
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
        store, "five_hour", used_pct=21.0, resets_at=5000.0,
        observed_at=2000.0, session_id="a"
    )
    assert [s["used_pct"] for s in store["five_hour"]] == [20.0, 21.0]


def test_record_projection_sample_rebaseline_drops_old_unit_samples(tmp_path):
    # Inputs reach this function AFTER reconcile_account, which (since
    # v3.13.3/4) gates stale session replays — so a converged reading BELOW
    # the recorded same-reset max means Anthropic re-baselined the limit
    # (observed live 2026-06-10: weekly 19% → 3%, same resets_at). Every
    # stored sample for that window is then in old-denominator units —
    # incomparable — so learning must restart instead of skipping new
    # samples until the old max is exceeded (which froze the →NN%
    # projection for the rest of the week).
    p = tmp_path / "projection.json"
    store = predict.load_projection_store(p)
    for used, ts in ((10.0, 1000.0), (19.0, 2000.0)):
        store = predict.record_projection_sample(
            store, "seven_day", used_pct=used, resets_at=600000.0,
            observed_at=ts, session_id="a"
        )
    # Seed display smoothing memory for both windows.
    store["display"]["seven_day"] = {"projected_pct": 100.0, "resets_at": 600000.0}
    store["display"]["five_hour"] = {"projected_pct": 40.0, "resets_at": 5000.0}
    store = predict.record_projection_sample(
        store, "seven_day", used_pct=3.0, resets_at=600000.0,
        observed_at=3000.0, session_id="a"
    )
    # Old-unit samples gone; the re-baselined reading is the new history.
    assert [s["used_pct"] for s in store["seven_day"]] == [3.0]
    # Display smoothing for the re-baselined window restarts; other window
    # untouched.
    assert "seven_day" not in store["display"]
    assert store["display"]["five_hour"]["projected_pct"] == 40.0


def test_record_projection_sample_accepts_earlier_reset_window(tmp_path):
    # Sessions logged into DIFFERENT accounts share the store (blob origin is
    # not in stdin), so windows with different resets_at must coexist: a sample
    # for an EARLIER reset (this account's real window) must still be recorded
    # while another account's later-reset samples exist — projection math
    # already selects samples per reset. Live incident 2026-06-12: the real
    # window's →NN% had no samples because "later reset wins" rejected them.
    p = tmp_path / "projection.json"
    store = predict.load_projection_store(p)
    store = predict.record_projection_sample(
        store, "seven_day", used_pct=14.0, resets_at=650000.0,
        observed_at=1000.0, session_id="other-account"
    )
    store = predict.record_projection_sample(
        store, "seven_day", used_pct=77.0, resets_at=600000.0,
        observed_at=1001.0, session_id="this-account"
    )
    by_reset = {s["resets_at"]: s["used_pct"] for s in store["seven_day"]}
    assert by_reset == {650000.0: 14.0, 600000.0: 77.0}


def test_record_projection_sample_rebaseline_scoped_to_its_reset(tmp_path):
    # A same-reset downward re-baseline restarts learning for THAT window
    # only — samples for a coexisting window (other account, different
    # resets_at) must survive.
    p = tmp_path / "projection.json"
    store = predict.load_projection_store(p)
    store = predict.record_projection_sample(
        store, "seven_day", used_pct=14.0, resets_at=650000.0,
        observed_at=1000.0, session_id="other-account"
    )
    store = predict.record_projection_sample(
        store, "seven_day", used_pct=19.0, resets_at=600000.0,
        observed_at=1001.0, session_id="this-account"
    )
    store = predict.record_projection_sample(
        store, "seven_day", used_pct=3.0, resets_at=600000.0,
        observed_at=2000.0, session_id="this-account"
    )
    by_reset = {s["resets_at"]: s["used_pct"] for s in store["seven_day"]}
    assert by_reset == {650000.0: 14.0, 600000.0: 3.0}


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


def test_learned_bucket_rates_accept_heavy_real_5h_burn(use_tz):
    # Live complaint 2026-06-12: parallel sessions really do burn the 5h
    # window at 30-40%/h (observed 54%→62% in 13 min), but the flat 20%/h
    # plausibility cap rejected every such delta, so heavy real usage taught
    # the model nothing and projections sat at "no growth". The cap is
    # window-aware now: 5h readings may move much faster than 7d ones.
    use_tz("Asia/Tokyo")
    reset = 1780927200.0
    samples = [
        {"observed_at": _ts(2026, 6, 1, 1, 0), "used_pct": 54.0, "resets_at": reset, "session_id": "s"},
        {"observed_at": _ts(2026, 6, 1, 1, 13), "used_pct": 62.0, "resets_at": reset, "session_id": "s"},
    ]
    rates = predict.learn_bucket_rates(samples, window="five_hour")
    assert rates["weekday_work_hours"]["samples"] == 1
    assert abs(rates["weekday_work_hours"]["rate_per_hour"] - 8.0 / (13 / 60)) < 1e-6


def test_learned_bucket_rates_keep_7d_cap_tight(use_tz):
    # The seven_day window can't really move 30%/h — that magnitude is a
    # glitch and must stay filtered.
    use_tz("Asia/Tokyo")
    reset = 1780927200.0
    samples = [
        {"observed_at": _ts(2026, 6, 1, 1, 0), "used_pct": 10.0, "resets_at": reset, "session_id": "s"},
        {"observed_at": _ts(2026, 6, 1, 1, 13), "used_pct": 18.0, "resets_at": reset, "session_id": "s"},
    ]
    rates = predict.learn_bucket_rates(samples, window="seven_day")
    assert rates.get("weekday_work_hours", {}).get("samples", 0) == 0


def test_rate_from_samples_accepts_heavy_5h_burn():
    now = 10_000.0
    reset = now + 720.0
    samples = [
        {"observed_at": now - 780, "used_pct": 54.0, "resets_at": reset, "session_id": "s"},
        {"observed_at": now, "used_pct": 62.0, "resets_at": reset, "session_id": "s"},
    ]
    rate = predict._rate_from_samples(samples, now, 3600.0, window="five_hour")
    assert rate is not None
    assert abs(rate - 8.0 / 780.0) < 1e-9


def test_rate_from_samples_needs_minimum_baseline():
    # Two readings seconds apart say nothing about pace (used_pct moves in
    # integer steps) — with the cap raised, a minimum observation span is the
    # glitch filter instead.
    now = 10_000.0
    reset = now + 720.0
    samples = [
        {"observed_at": now - 30, "used_pct": 54.0, "resets_at": reset, "session_id": "s"},
        {"observed_at": now, "used_pct": 62.0, "resets_at": reset, "session_id": "s"},
    ]
    assert predict._rate_from_samples(samples, now, 3600.0, window="five_hour") is None


def test_project_5h_reflects_heavy_burn_instead_of_flatlining():
    # 62% with 12 min left, burning ~37%/h for the last 13 min: the projection
    # must move meaningfully above "you stop right now".
    now = 10_000.0
    reset = now + 720.0
    samples = [
        {"observed_at": now - 780, "used_pct": 54.0, "resets_at": reset, "session_id": "s"},
        {"observed_at": now, "used_pct": 62.0, "resets_at": reset, "session_id": "s"},
    ]
    projected = predict.project_5h(62.0, reset, now, samples)
    assert projected >= 65.0
    assert projected <= 100.0


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


def test_project_7d_active_burn_lifts_near_term_projection(use_tz):
    # Live complaint 2026-06-12: 79% used, actively burning ~2%/h for hours —
    # yet the projection barely moved because it integrated bucket rates only
    # and ignored current momentum. Scenario pinned to a NIGHT stretch (prior
    # ≈0, no learned samples in that bucket) so only the momentum term can
    # lift the result: burning through the evening, 4h to reset at 03:00.
    use_tz("Asia/Tokyo")
    now = _ts(2026, 6, 9, 14)            # Tue 23:00 JST
    reset = now + 4 * 3600.0             # 03:00 JST — night bucket throughout
    samples = [
        {"observed_at": now - 3 * 3600 + i * 1800, "used_pct": 73.0 + i,
         "resets_at": reset, "session_id": "s"}
        for i in range(7)                # 20:00→23:00 JST, 2%/h
    ]
    projected = predict.project_7d(79.0, reset, now, samples)
    # ~2%/h carried over the next 3h ⇒ ≥ +5 over "you stop right now";
    # bucket integration alone gives ≈ 79.1.
    assert projected >= 84.0
    assert projected <= 100.0


def test_project_7d_momentum_never_lowers_bucket_estimate():
    # An idle stretch (no positive recent rate) must leave the bucket-based
    # projection untouched.
    now = 1_781_000_000.0
    reset = now + 39 * 3600.0
    flat = [
        {"observed_at": now - 3 * 3600, "used_pct": 79.0, "resets_at": reset, "session_id": "s"},
        {"observed_at": now, "used_pct": 79.0, "resets_at": reset, "session_id": "s"},
    ]
    assert predict.project_7d(79.0, reset, now, flat) == predict.project_7d(79.0, reset, now, [])


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

    # The fresh session's reading lands in rate_latest via the recording
    # reconcile (core.main's first call); projection() itself is read-only.
    predict.reconcile_account(20.0, reset, 15.0, now + 6 * 86400, now=now)
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


def test_projection_shown_even_when_equals_current(tmp_path, monkeypatch):
    """Near reset / flat window: projection ≈ current usage is still shown (it's
    honest — "you'll end about here" — not hidden)."""
    import claude_statusbar.predict as predict
    monkeypatch.setattr(predict, "_PROJECTION_PATH", tmp_path / "proj.json")
    monkeypatch.setattr(predict, "_LATEST_PATH", tmp_path / "latest.json")
    now = 1_000_000.0
    # used 5% with 10 min to reset → window-avg projects ~5% (≈ current) → still shown.
    store = predict.empty_projection_store()
    chip = predict._projection_for_window(store, "five_hour", 5.0, now + 600, now, "s")
    assert chip.startswith("→") and chip.endswith("%")


def test_projection_shown_when_growth_predicted(tmp_path, monkeypatch):
    import claude_statusbar.predict as predict
    monkeypatch.setattr(predict, "_PROJECTION_PATH", tmp_path / "proj.json")
    monkeypatch.setattr(predict, "_LATEST_PATH", tmp_path / "latest.json")
    now = 1_000_000.0
    # used 10% with 2 h to reset (early-ish 5h window) → projects well above 10%.
    store = predict.empty_projection_store()
    chip = predict._projection_for_window(store, "five_hour", 10.0, now + 7200, now, "s")
    assert chip.startswith("→") and chip != "→10%"


def test_projection_holds_placeholder_before_min_elapsed(tmp_path, monkeypatch):
    """Fresh window, only a few minutes elapsed: a couple of coarse integer
    steps say nothing about pace, so the projection holds the `→--` placeholder
    rather than shipping a fake-precise (and badly low) number. Regression for
    the live `→14%` at ~6 min into a 5h window (2026-06-16)."""
    import claude_statusbar.predict as predict
    monkeypatch.setattr(predict, "_PROJECTION_PATH", tmp_path / "proj.json")
    monkeypatch.setattr(predict, "_LATEST_PATH", tmp_path / "latest.json")
    L = predict.WINDOW_LEN_S["five_hour"]
    reset = 2_000_000.0
    store = predict.empty_projection_store()
    # elapsed 6 min (< MIN_ELAPSED 10 min), used 1%
    now = reset - L + 6 * 60
    chip = predict._projection_for_window(store, "five_hour", 1.0, reset, now, "s")
    assert chip == predict.DEBUG_PLACEHOLDER
    # the no-signal tick must NOT have seeded a (low) display projection
    assert "five_hour" not in store.get("display", {})


def test_early_zero_tick_does_not_poison_later_projection(tmp_path, monkeypatch):
    """The used=0 first post-reset tick must not seed the smoother near zero and
    drag the projection down for ~15 min. Once past MIN_ELAPSED the smoother
    seeds from the first trustworthy raw, so the projection reflects the real
    pace, not a lagged near-zero value."""
    import claude_statusbar.predict as predict
    monkeypatch.setattr(predict, "_PROJECTION_PATH", tmp_path / "proj.json")
    monkeypatch.setattr(predict, "_LATEST_PATH", tmp_path / "latest.json")
    L = predict.WINDOW_LEN_S["five_hour"]
    reset = 2_000_000.0
    store = predict.empty_projection_store()
    # early ticks (all < 10 min elapsed): used climbs 0 → 1 → 2, all placeholder
    for el_min, used in [(1, 0.0), (4, 1.0), (7, 2.0)]:
        now = reset - L + el_min * 60
        chip = predict._projection_for_window(store, "five_hour", used, reset, now, "s")
        assert chip == predict.DEBUG_PLACEHOLDER
    # first tick past MIN_ELAPSED: seeds fresh from raw, well above the bogus
    # ~14% an EMA-from-zero would have produced.
    now = reset - L + 12 * 60
    chip = predict._projection_for_window(store, "five_hour", 3.0, reset, now, "s")
    val = float(chip.lstrip("→").rstrip("%"))
    assert val > 30.0, f"projection {chip} still lagging — EMA seeded from zero"


def test_depletion_eta_appended_when_projection_maxes(monkeypatch, tmp_path):
    """User request (2026-07-10): `→100%` alone hides the useful half of the
    prediction. When the pace overshoots the cap, the chip carries the time
    until the quota actually runs out: `→100%·1h15m`."""
    import re
    monkeypatch.setattr(predict, "_projection_path",
                        lambda: tmp_path / "proj.json")
    monkeypatch.setattr(predict, "_latest_path", lambda: tmp_path / "latest.json")

    now = 1_800_000_000.0
    reset = now + 2 * 3600           # 2h to reset
    # 3h into a 5h window at 80% used → pace 26.7%/h → 100% in ~45min.
    samples = [
        {"observed_at": now - 3600, "used_pct": 53.0},
        {"observed_at": now - 1800, "used_pct": 67.0},
        {"observed_at": now, "used_pct": 80.0},
    ]
    store = predict.empty_projection_store()
    store["five_hour"] = samples
    chip = predict._projection_for_window(store, "five_hour", 80.0, reset,
                                          now, "sid")
    assert chip.startswith("→100%·"), chip
    eta = chip.split("·", 1)[1]
    assert re.fullmatch(r"(<1m|\d+m|\d+h(\d{2}m)?)", eta), chip

    # The severity parser still reads the percent out of the extended chip.
    from claude_statusbar.progress import projection_pct
    assert projection_pct(chip) == 100.0


def test_no_eta_when_projection_below_cap(monkeypatch, tmp_path):
    monkeypatch.setattr(predict, "_projection_path",
                        lambda: tmp_path / "proj.json")
    monkeypatch.setattr(predict, "_latest_path", lambda: tmp_path / "latest.json")
    now = 1_800_000_000.0
    reset = now + 2 * 3600
    samples = [
        {"observed_at": now - 3600, "used_pct": 19.0},
        {"observed_at": now, "used_pct": 20.0},   # 1%/h — nowhere near the cap
    ]
    store = predict.empty_projection_store()
    store["five_hour"] = samples
    chip = predict._projection_for_window(store, "five_hour", 20.0, reset,
                                          now, "sid")
    assert "·" not in chip, chip


def test_depletion_eta_math():
    # 80% used, 2h to reset, projection says 120% → hits 100 at half the window.
    eta = predict._depletion_eta_seconds(80.0, 7200.0, 120.0)
    assert eta == 7200.0 * 20.0 / 40.0
    assert predict._depletion_eta_seconds(80.0, 7200.0, 95.0) is None     # under cap
    assert predict._depletion_eta_seconds(100.0, 7200.0, 120.0) is None  # already empty
    assert predict._depletion_eta_seconds(80.0, 0.0, 120.0) is None      # reset now


def test_legacy_forecast_chip_yields_to_projection_eta():
    """`⚠~25m` (average-pace) and `→100%·33m` (blended-rate) answer the same
    question; two disagreeing countdowns must not sit side by side. The legacy
    chip renders only when the projection carries no ETA."""
    from claude_statusbar.progress import format_status_line
    from claude_statusbar.themes import get_theme

    kw = dict(msgs_pct=72, tkns_pct=72, weekly_pct=50, model="Opus",
              reset_time="3h54m", theme=get_theme("graphite"), use_color=False)
    both = format_status_line(projection_5h="→100%·33m", forecast_5h="~25m", **kw)
    assert "·33m" in both and "~25m" not in both

    # ANY usable projection silences the legacy chip — `→98% ⚠~25m` (seen
    # live) had the better model saying "ends under the cap" next to the
    # cruder one screaming "empty in 25m".
    contradiction = format_status_line(projection_5h="→98%", forecast_5h="~25m", **kw)
    assert "~25m" not in contradiction
    at_cap_no_eta = format_status_line(projection_5h="→100%", forecast_5h="~25m", **kw)
    assert "~25m" not in at_cap_no_eta

    # No projection at all (off, or early-window placeholder) → legacy fallback.
    only_legacy = format_status_line(projection_5h="", forecast_5h="~25m", **kw)
    assert "~25m" in only_legacy
    placeholder = format_status_line(projection_5h="→--", forecast_5h="~25m", **kw)
    assert "~25m" in placeholder


def test_snapshots_are_throttled_per_window():
    """Unthrottled snapshots (one per compute, ~0.4s apart live) rolled the
    1000-entry cap in 8.5 minutes and dominated the daemon's JSON cost."""
    store = predict.empty_projection_store()
    t0 = 1_800_000_000.0
    for i in range(120):
        predict.record_projection_snapshot(store, "five_hour", t0 + i, 50.0,
                                           t0 + 7200, 80.0)
    assert len(store["snapshots"]) == 2  # t0 and t0+60 — one per MIN_GAP
    # Windows throttle independently.
    predict.record_projection_snapshot(store, "seven_day", t0 + 1, 20.0,
                                       t0 + 86400, 30.0)
    assert len(store["snapshots"]) == 3


def test_samples_are_decimated():
    """Fractional-percent ticks every second are file weight, not signal —
    2032 stored samples ≈ 2/3 of a 313KB store re-parsed each second."""
    store = predict.empty_projection_store()
    t0 = 1_800_000_000.0
    reset = t0 + 4 * 3600
    for i in range(45):
        predict.record_projection_sample(store, "five_hour", 50.0 + i * 0.01,
                                         reset, t0 + i)
    assert len(store["five_hour"]) == 1  # sub-0.5pp AND sub-60s → skipped
    # A ≥0.5pp jump lands immediately…
    predict.record_projection_sample(store, "five_hour", 50.6, reset, t0 + 45.5)
    assert len(store["five_hour"]) == 2
    # …and a slow trickle still lands once 60s elapse.
    predict.record_projection_sample(store, "five_hour", 50.61, reset, t0 + 106)
    assert len(store["five_hour"]) == 3


def test_over_cap_rate_clamps_instead_of_vanishing():
    """Discarding over-cap rates made the projection fall back to the window
    average at exactly the hottest moments — low when it should be high."""
    now = 1_800_000_000.0
    # 80%/h over 10 minutes — above the 60%/h 5h cap.
    samples = [
        {"observed_at": now - 600, "used_pct": 40.0, "resets_at": now + 3600},
        {"observed_at": now, "used_pct": 53.3, "resets_at": now + 3600},
    ]
    rate = predict._rate_from_samples(samples, now, 3600.0, window="five_hour")
    assert rate is not None, "burst rate must not vanish"
    assert rate == predict.RATE_CAP_PCT_PER_H["five_hour"] / 3600.0


def test_smoothing_approaches_fast_when_depleting():
    """Easing toward a ≥100% raw over the full 8-minute tau delayed the
    →100%·ETA warning by minutes; the approach is fast on the way up and
    stays slow on the way down (no flapping on cooldown)."""
    t0 = 1_800_000_000.0
    prev = {"projected_pct": 85.0, "updated_at": t0}
    up = predict.smooth_projection("five_hour", 110.0, 80.0, t0 + 60, prev)
    # With tau=480 a 60s step moves ~12%; with tau=120 it moves ~39%.
    assert up["projected_pct"] > 90.0, up
    down = predict.smooth_projection("five_hour", 60.0, 55.0,
                                     t0 + 60, {"projected_pct": 100.0, "updated_at": t0})
    # Downward keeps the slow tau: barely moved in 60s.
    assert down["projected_pct"] > 92.0, down


def test_legacy_dense_snapshots_are_redecimated_on_append():
    """Stores written before throttling hold ~1000 entries at 0.4s spacing;
    at one append per minute they'd stay fat for ~8 hours. One append
    re-decimates the whole list to the 60s grid."""
    store = predict.empty_projection_store()
    t0 = 1_800_000_000.0
    store["snapshots"] = [
        {"window": "five_hour", "observed_at": t0 + i * 0.4, "used_pct": 50.0,
         "resets_at": t0 + 7200, "model": "projection_v1", "projected_pct": 80.0}
        for i in range(900)
    ]
    predict.record_projection_snapshot(store, "five_hour", t0 + 3600, 60.0,
                                       t0 + 7200, 85.0)
    snaps = store["snapshots"]
    assert len(snaps) <= 8, f"legacy density survived: {len(snaps)} entries"
    times = [s["observed_at"] for s in snaps]
    assert all(b - a >= predict.SNAPSHOT_MIN_GAP_S for a, b in zip(times, times[1:]))
