# Rate-limit Projection Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build always-visible `5h →NN%` and `7d →NN%` end-of-window projections that learn from local usage history, smooth by wall-clock/sample time, and log prediction error against actual reset outcomes.

**Architecture:** Extend `src/claude_statusbar/predict.py` from at-risk ETA helpers into the rate-limit prediction module: keep existing ETA functions, add a bounded account-global projection store, sample recording, coarse bucket learning, projection math, smoothing, and metrics. `core.main` computes both ETA chips and projection chips from official rate-limit stdin, then passes raw strings to `progress.format_status_line` through `styles.render_classic`.

**Tech Stack:** Python 3.9+ stdlib only (`json`, `math`, `time`, `pathlib`, `dataclasses` optional). Tests use `pytest` with `PYTHONPATH=src`. Persistence reuses `claude_statusbar.cache.atomic_write_text`.

---

## File Structure

- Modify `src/claude_statusbar/predict.py`
  - Keep existing `format_eta`, `project_window`, `forecast_chip`, `reconcile_account`, and `forecast` behavior for `⚠~ETA`.
  - Add projection store helpers, sample recording, coarse buckets, learned rates, smoothing, metrics, and `projection(...)`.
- Modify `src/claude_statusbar/config.py`
  - Add `show_projection: bool = True`.
  - Add config validation and bool parsing for `show_projection`.
- Modify `src/claude_statusbar/cli.py`
  - Show `show_projection` in `cs config show`.
- Modify `src/claude_statusbar/core.py`
  - Call `predict.projection(...)` when official rate-limit data exists and config enables it.
  - Keep `show_forecast` dedicated to `⚠~ETA`.
- Modify `src/claude_statusbar/progress.py`
  - Add `projection_5h` / `projection_7d` render slots after each reset timer and before forecast ETA.
- Modify `src/claude_statusbar/styles.py`
  - Thread projection strings through `render_classic` and `styles.render`.
- Modify docs after implementation:
  - `README.md`
  - `CHANGELOG.md`
- Tests:
  - Create or expand `tests/test_projection.py`.
  - Modify `tests/test_forecast_render.py`.
  - Modify `tests/test_config_forecast.py` or add `tests/test_config_projection.py`.
  - Modify `tests/test_core_forecast_guard.py` or add `tests/test_core_projection.py`.

---

### Task 1: Config and Render Contract

**Files:**
- Modify: `src/claude_statusbar/config.py`
- Modify: `src/claude_statusbar/cli.py`
- Modify: `src/claude_statusbar/progress.py`
- Modify: `src/claude_statusbar/styles.py`
- Test: `tests/test_config_projection.py`
- Test: `tests/test_forecast_render.py`

- [ ] **Step 1: Write failing config tests**

Add `tests/test_config_projection.py`:

```python
from claude_statusbar.config import StatusbarConfig, load_config, set_value


def test_projection_default_on():
    assert StatusbarConfig().show_projection is True


def test_projection_set_and_load(tmp_path):
    p = tmp_path / "cfg.json"
    set_value("show_projection", "false", p)
    assert load_config(p).show_projection is False
```

- [ ] **Step 2: Run config test and verify it fails**

Run:

```bash
PYTHONPATH=src pytest tests/test_config_projection.py -q
```

Expected: FAIL because `StatusbarConfig` has no `show_projection`.

- [ ] **Step 3: Implement config wiring**

In `src/claude_statusbar/config.py`:

```python
@dataclass
class StatusbarConfig:
    # existing fields...
    show_forecast: bool = True
    show_projection: bool = True
    forecast_debug: bool = False
```

In `load_config(...)`, add:

```python
show_projection=_to_bool(raw.get("show_projection", True)),
```

Add `"show_projection"` to `VALID_KEYS` and `_BOOL_KEYS`.

In `src/claude_statusbar/cli.py`, inside config show output, add:

```python
print(f"show_projection     = {cfg.show_projection}")
```

- [ ] **Step 4: Run config tests**

Run:

```bash
PYTHONPATH=src pytest tests/test_config_projection.py tests/test_config_show_keys.py -q
```

Expected: PASS.

- [ ] **Step 5: Write failing render tests**

Append to `tests/test_forecast_render.py`:

```python
def test_projection_after_reset_before_eta():
    out = format_status_line(
        msgs_pct=80,
        tkns_pct=None,
        reset_time="1h28m",
        model="Opus",
        weekly_pct=10,
        reset_time_7d="6d",
        use_color=False,
        theme=TH,
        projection_5h="→92%",
        forecast_5h="~40m",
    )
    assert out.index("→92%") > out.index("1h28m")
    assert out.index("→92%") < out.index("~40m")


def test_projection_after_7d_reset():
    out = format_status_line(
        msgs_pct=10,
        tkns_pct=None,
        reset_time="1h",
        model="Opus",
        weekly_pct=30,
        reset_time_7d="6d05h",
        use_color=False,
        theme=TH,
        projection_7d="→67%",
    )
    assert out.index("→67%") > out.index("6d05h")


def test_no_projection_when_absent():
    out = format_status_line(
        msgs_pct=10,
        tkns_pct=None,
        reset_time="1h",
        model="Opus",
        weekly_pct=30,
        reset_time_7d="6d05h",
        use_color=False,
        theme=TH,
    )
    assert "→" not in out
```

- [ ] **Step 6: Run render tests and verify they fail**

Run:

```bash
PYTHONPATH=src pytest tests/test_forecast_render.py -q
```

Expected: FAIL because `format_status_line` does not accept `projection_5h` / `projection_7d`.

- [ ] **Step 7: Implement render slots**

In `src/claude_statusbar/progress.py`, extend `format_status_line(...)`:

```python
def format_status_line(
    msgs_pct, tkns_pct, reset_time, model,
    weekly_pct=None, reset_time_7d="",
    ctx_pct=None,
    bypass=False, use_color=True,
    countdown_emoji="",
    warning_threshold=None, critical_threshold=None,
    lang_text="", cost_text="",
    theme=None,
    shimmer_phase=None,
    projection_5h: str = "",
    projection_7d: str = "",
    forecast_5h: str = "",
    forecast_7d: str = "",
):
```

Add helper:

```python
def _render_projection(chip: str, theme, use_color: bool) -> str:
    return colorize(chip, _fg(theme.mute), use_color)
```

Insert projection before forecast:

```python
dim_5h += colorize(f"⏰{reset_time}{countdown_emoji}", color_5h, use_color)
if projection_5h:
    dim_5h += " " + _render_projection(projection_5h, theme, use_color)
if forecast_5h:
    dim_5h += " " + _render_forecast(forecast_5h, theme, use_color)
```

And for 7d:

```python
if reset_time_7d:
    dim_7d += colorize(f"⏰{reset_time_7d}", color_7d, use_color)
if projection_7d:
    dim_7d += " " + _render_projection(projection_7d, theme, use_color)
if forecast_7d:
    dim_7d += " " + _render_forecast(forecast_7d, theme, use_color)
```

In `src/claude_statusbar/styles.py`, add `projection_5h` and `projection_7d` parameters to `render_classic(...)` and forward them into `format_status_line(...)`.

- [ ] **Step 8: Run render/config tests**

Run:

```bash
PYTHONPATH=src pytest tests/test_forecast_render.py tests/test_config_projection.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/claude_statusbar/config.py src/claude_statusbar/cli.py src/claude_statusbar/progress.py src/claude_statusbar/styles.py tests/test_config_projection.py tests/test_forecast_render.py
git commit -m "feat: wire rate-limit projection display"
```

---

### Task 2: Projection Store and Sample Recording

**Files:**
- Modify: `src/claude_statusbar/predict.py`
- Test: `tests/test_projection.py`

- [ ] **Step 1: Write failing store tests**

Create `tests/test_projection.py`:

```python
import json

from claude_statusbar import predict


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


def test_record_projection_sample_prunes_bounded_history(tmp_path, monkeypatch):
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
```

- [ ] **Step 2: Run store tests and verify they fail**

Run:

```bash
PYTHONPATH=src pytest tests/test_projection.py -q
```

Expected: FAIL because projection store functions do not exist.

- [ ] **Step 3: Implement store helpers**

In `src/claude_statusbar/predict.py`, add:

```python
import math
from typing import Any, Dict, List

MAX_PROJECTION_SAMPLES = 5000
MAX_PROJECTION_SNAPSHOTS = 1000
MAX_CLOSED_WINDOWS = 100
_PROJECTION_PATH = Path(os.path.expanduser("~")) / ".cache" / "claude-statusbar" / "rate_projection.json"


def empty_projection_store() -> Dict[str, Any]:
    return {
        "version": 1,
        "five_hour": [],
        "seven_day": [],
        "display": {},
        "snapshots": [],
        "closed_windows": [],
    }


def load_projection_store(path=None) -> Dict[str, Any]:
    p = Path(path) if path is not None else _PROJECTION_PATH
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return empty_projection_store()
    except (OSError, json.JSONDecodeError, ValueError):
        return empty_projection_store()
    store = empty_projection_store()
    store.update({k: data.get(k, store[k]) for k in store})
    for key in ("five_hour", "seven_day", "snapshots", "closed_windows"):
        if not isinstance(store.get(key), list):
            store[key] = []
    if not isinstance(store.get("display"), dict):
        store["display"] = {}
    store["version"] = 1
    return store


def save_projection_store(store: Dict[str, Any], path=None) -> None:
    p = Path(path) if path is not None else _PROJECTION_PATH
    from .cache import atomic_write_text
    atomic_write_text(p, json.dumps(store, separators=(",", ":")))


def _valid_window(window: str) -> bool:
    return window in WINDOW_LEN_S


def record_projection_sample(store: Dict[str, Any], window: str, used_pct, resets_at,
                             observed_at: float, session_id: str = "") -> Dict[str, Any]:
    if not _valid_window(window):
        return store
    try:
        used = float(used_pct)
        reset = float(resets_at)
        ts = float(observed_at)
    except (TypeError, ValueError):
        return store
    if ts <= 0 or reset <= 0 or used < 0:
        return store
    sample = {
        "observed_at": ts,
        "used_pct": max(0.0, min(100.0, used)),
        "resets_at": reset,
        "session_id": str(session_id or ""),
    }
    series = store.setdefault(window, [])
    if not isinstance(series, list):
        series = []
        store[window] = series
    if series and series[-1] == sample:
        return store
    series.append(sample)
    series.sort(key=lambda s: float(s.get("observed_at", 0.0)))
    del series[:-MAX_PROJECTION_SAMPLES]
    return store
```

- [ ] **Step 4: Run store tests**

Run:

```bash
PYTHONPATH=src pytest tests/test_projection.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/claude_statusbar/predict.py tests/test_projection.py
git commit -m "feat: add rate projection history store"
```

---

### Task 3: Buckets, Learned Rates, and 7d Integration

**Files:**
- Modify: `src/claude_statusbar/predict.py`
- Test: `tests/test_projection.py`

- [ ] **Step 1: Add failing bucket tests**

Append to `tests/test_projection.py`:

```python
def test_bucket_for_time_distinguishes_weekday_work_weekend_and_night():
    # 2026-06-01 10:00:00 UTC is Monday 19:00 in Asia/Tokyo, a weekday non-work bucket.
    assert predict.bucket_for_time(1780327200.0) == "weekday_non_work_hours"
    # 2026-06-01 01:00:00 UTC is Monday 10:00 in Asia/Tokyo, a weekday work bucket.
    assert predict.bucket_for_time(1780294800.0) == "weekday_work_hours"
    # 2026-06-01 18:00:00 UTC is Tuesday 03:00 in Asia/Tokyo, night.
    assert predict.bucket_for_time(1780356000.0) == "night"
    # 2026-06-06 03:00:00 UTC is Saturday 12:00 in Asia/Tokyo, weekend.
    assert predict.bucket_for_time(1780714800.0) == "weekend"


def test_learned_bucket_rates_from_positive_deltas():
    samples = [
        {"observed_at": 1780294800.0, "used_pct": 10.0, "resets_at": 1780927200.0, "session_id": "s"},
        {"observed_at": 1780298400.0, "used_pct": 12.0, "resets_at": 1780927200.0, "session_id": "s"},
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
    # Start Monday 10:00 Tokyo and integrate 2 hours of work time.
    start = 1780294800.0
    end = start + 2 * 3600
    usage = predict.integrate_future_buckets(start, end, {})
    expected = 2 * predict.DEFAULT_BUCKET_PRIORS["weekday_work_hours"]
    assert abs(usage - expected) < 1e-6
```

- [ ] **Step 2: Run bucket tests and verify they fail**

Run:

```bash
PYTHONPATH=src pytest tests/test_projection.py -q
```

Expected: FAIL because bucket helpers do not exist.

- [ ] **Step 3: Implement bucket helpers**

In `src/claude_statusbar/predict.py`, add:

```python
from datetime import datetime, timezone, timedelta

LOCAL_OFFSET = timedelta(hours=9)  # Asia/Tokyo, no DST.
DEFAULT_BUCKET_PRIORS = {
    "night": 0.02,
    "weekday_work_hours": 0.45,
    "weekday_non_work_hours": 0.12,
    "weekend": 0.10,
}
LEARNED_BUCKET_FULL_WEIGHT_SAMPLES = 20


def _local_datetime(ts: float) -> datetime:
    return datetime.fromtimestamp(float(ts), tz=timezone.utc) + LOCAL_OFFSET


def bucket_for_time(ts: float) -> str:
    dt = _local_datetime(ts)
    hour = dt.hour
    if hour < 7:
        return "night"
    if dt.weekday() >= 5:
        return "weekend"
    if 9 <= hour < 18:
        return "weekday_work_hours"
    return "weekday_non_work_hours"


def learn_bucket_rates(samples: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}
    ordered = sorted(samples, key=lambda s: float(s.get("observed_at", 0.0)))
    for prev, cur in zip(ordered, ordered[1:]):
        try:
            dt = float(cur["observed_at"]) - float(prev["observed_at"])
            du = float(cur["used_pct"]) - float(prev["used_pct"])
        except (KeyError, TypeError, ValueError):
            continue
        if dt < 300 or du <= 0:
            continue
        rate_per_hour = du / (dt / 3600.0)
        if rate_per_hour > 20.0:
            continue
        bucket = bucket_for_time(float(prev["observed_at"]))
        agg = out.setdefault(bucket, {"total_rate": 0.0, "samples": 0})
        agg["total_rate"] += rate_per_hour
        agg["samples"] += 1
    for bucket, agg in out.items():
        samples_n = int(agg["samples"])
        agg["rate_per_hour"] = agg["total_rate"] / samples_n if samples_n else DEFAULT_BUCKET_PRIORS[bucket]
    return out


def expected_bucket_rate(bucket: str, learned: Dict[str, float] = None) -> float:
    prior = DEFAULT_BUCKET_PRIORS.get(bucket, 0.0)
    if not learned:
        return prior
    try:
        learned_rate = float(learned.get("rate_per_hour", prior))
        samples_n = max(0.0, float(learned.get("samples", 0.0)))
    except (TypeError, ValueError):
        return prior
    weight = min(1.0, samples_n / LEARNED_BUCKET_FULL_WEIGHT_SAMPLES)
    return prior * (1.0 - weight) + learned_rate * weight


def integrate_future_buckets(start_ts: float, end_ts: float,
                             learned_rates: Dict[str, Dict[str, float]]) -> float:
    start = float(start_ts)
    end = float(end_ts)
    if end <= start:
        return 0.0
    total = 0.0
    cursor = start
    while cursor < end:
        step_end = min(end, cursor + 3600.0)
        bucket = bucket_for_time(cursor)
        rate = expected_bucket_rate(bucket, learned_rates.get(bucket, {}))
        total += rate * ((step_end - cursor) / 3600.0)
        cursor = step_end
    return total
```

- [ ] **Step 4: Run bucket tests**

Run:

```bash
PYTHONPATH=src pytest tests/test_projection.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/claude_statusbar/predict.py tests/test_projection.py
git commit -m "feat: add coarse projection buckets"
```

---

### Task 4: Projection Math, Smoothing, and Metrics

**Files:**
- Modify: `src/claude_statusbar/predict.py`
- Test: `tests/test_projection.py`

- [ ] **Step 1: Add failing projection tests**

Append to `tests/test_projection.py`:

```python
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
```

- [ ] **Step 2: Run projection tests and verify they fail**

Run:

```bash
PYTHONPATH=src pytest tests/test_projection.py -q
```

Expected: FAIL because projection, smoothing, and closing helpers do not exist.

- [ ] **Step 3: Implement projection math**

In `src/claude_statusbar/predict.py`, add:

```python
TAU_SECONDS = {"five_hour": 8 * 60, "seven_day": 2 * 3600}


def _samples_for_reset(samples: List[Dict[str, Any]], resets_at: float) -> List[Dict[str, Any]]:
    return [s for s in samples if _coerce(s.get("resets_at")) == float(resets_at)]


def _rate_from_samples(samples: List[Dict[str, Any]], now: float, lookback_s: float) -> Optional[float]:
    cutoff = now - lookback_s
    in_window = [s for s in samples if float(s.get("observed_at", 0.0)) >= cutoff]
    if len(in_window) < 2:
        return None
    first, last = in_window[0], in_window[-1]
    dt = float(last["observed_at"]) - float(first["observed_at"])
    du = float(last["used_pct"]) - float(first["used_pct"])
    if dt <= 0 or du <= 0:
        return None
    rate = du / dt
    if rate > 20.0 / 3600.0:
        return None
    return rate


def project_5h(current_used: float, resets_at: float, now: float,
               samples: List[Dict[str, Any]]) -> float:
    ttr = max(0.0, float(resets_at) - float(now))
    window_avg = project_window(current_used, ttr, WINDOW_LEN_S["five_hour"])
    avg_rate = None
    if window_avg is not None:
        projected_final, _ttl = window_avg
        avg_rate = max(0.0, (projected_final - float(current_used)) / ttr) if ttr > 0 else 0.0
    recent = _rate_from_samples(samples, float(now), 3600.0)
    learned = learn_bucket_rates(samples)
    bucket_rate_per_hour = expected_bucket_rate(bucket_for_time(now), learned.get(bucket_for_time(now), {}))
    bucket_rate = bucket_rate_per_hour / 3600.0
    rates = []
    weights = []
    if recent is not None:
        rates.append(recent); weights.append(0.55)
    if avg_rate is not None:
        rates.append(avg_rate); weights.append(0.30 if recent is not None else 0.75)
    rates.append(bucket_rate); weights.append(0.15 if recent is not None else 0.25)
    total_w = sum(weights)
    blended = sum(r * w for r, w in zip(rates, weights)) / total_w if total_w else 0.0
    return max(float(current_used), min(100.0, float(current_used) + blended * ttr))


def project_7d(current_used: float, resets_at: float, now: float,
               samples: List[Dict[str, Any]]) -> float:
    learned = learn_bucket_rates(samples)
    future = integrate_future_buckets(float(now), float(resets_at), learned)
    ttr = max(0.0, float(resets_at) - float(now))
    window_avg = project_window(current_used, ttr, WINDOW_LEN_S["seven_day"])
    sanity = 0.0
    if window_avg is not None:
        sanity = max(0.0, window_avg[0] - float(current_used)) * 0.10
    return max(float(current_used), min(100.0, float(current_used) + future + sanity))


def smooth_projection(window: str, raw: float, current_used: float,
                      observed_at: float, previous: Dict[str, Any] = None) -> Dict[str, float]:
    raw = max(float(current_used), min(100.0, float(raw)))
    if not previous:
        return {"projected_pct": raw, "updated_at": float(observed_at)}
    prev_ts = _coerce(previous.get("updated_at"))
    prev_pct = _coerce(previous.get("projected_pct"))
    if prev_ts is None or prev_pct is None or float(observed_at) <= prev_ts:
        return {"projected_pct": max(float(current_used), min(100.0, prev_pct if prev_pct is not None else raw)),
                "updated_at": float(observed_at)}
    tau = TAU_SECONDS.get(window, 900)
    alpha = 1.0 - math.exp(-(float(observed_at) - prev_ts) / tau)
    smoothed = prev_pct * (1.0 - alpha) + raw * alpha
    return {"projected_pct": max(float(current_used), min(100.0, smoothed)),
            "updated_at": float(observed_at)}
```

- [ ] **Step 4: Implement metrics helpers**

In `src/claude_statusbar/predict.py`, add:

```python
def record_projection_snapshot(store: Dict[str, Any], window: str, observed_at: float,
                               used_pct: float, resets_at: float, projected_pct: float) -> Dict[str, Any]:
    snap = {
        "window": window,
        "observed_at": float(observed_at),
        "used_pct": float(used_pct),
        "resets_at": float(resets_at),
        "model": "projection_v1",
        "projected_pct": float(projected_pct),
    }
    snaps = store.setdefault("snapshots", [])
    snaps.append(snap)
    del snaps[:-MAX_PROJECTION_SNAPSHOTS]
    return store


def close_changed_windows(store: Dict[str, Any], window: str) -> Dict[str, Any]:
    series = store.get(window, [])
    if not isinstance(series, list) or len(series) < 2:
        return store
    closed = store.setdefault("closed_windows", [])
    seen = {(c.get("window"), c.get("previous_resets_at")) for c in closed if isinstance(c, dict)}
    for prev, cur in zip(series, series[1:]):
        prev_reset = prev.get("resets_at")
        cur_reset = cur.get("resets_at")
        if prev_reset != cur_reset and (window, prev_reset) not in seen:
            closed.append({
                "window": window,
                "previous_resets_at": prev_reset,
                "actual_final_pct": prev.get("used_pct"),
                "closed_at": cur.get("observed_at"),
            })
            seen.add((window, prev_reset))
    del closed[:-MAX_CLOSED_WINDOWS]
    return store
```

- [ ] **Step 5: Run projection tests**

Run:

```bash
PYTHONPATH=src pytest tests/test_projection.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/claude_statusbar/predict.py tests/test_projection.py
git commit -m "feat: compute learned rate-limit projections"
```

---

### Task 5: Projection Orchestrator and Core Integration

**Files:**
- Modify: `src/claude_statusbar/predict.py`
- Modify: `src/claude_statusbar/core.py`
- Test: `tests/test_core_projection.py`

- [ ] **Step 1: Add failing orchestrator tests**

Append to `tests/test_projection.py`:

```python
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
```

- [ ] **Step 2: Implement projection orchestrator**

In `src/claude_statusbar/predict.py`, add:

```python
def _format_projection_pct(value: float) -> str:
    return f"→{max(0.0, min(100.0, float(value))):.0f}%"


def _projection_for_window(store: Dict[str, Any], window: str, used_pct, resets_at,
                           now: float, session_id: str) -> str:
    try:
        used = float(used_pct)
        reset = float(resets_at)
    except (TypeError, ValueError):
        prev = store.get("display", {}).get(window, {})
        prev_pct = _coerce(prev.get("projected_pct")) if isinstance(prev, dict) else None
        return _format_projection_pct(prev_pct if prev_pct is not None else 0.0)
    store = record_projection_sample(store, window, used, reset, now, session_id)
    close_changed_windows(store, window)
    samples = _samples_for_reset(store.get(window, []), reset)
    raw = project_5h(used, reset, now, samples) if window == "five_hour" else project_7d(used, reset, now, samples)
    display = store.setdefault("display", {})
    previous = display.get(window) if isinstance(display.get(window), dict) else None
    display[window] = smooth_projection(window, raw, used, now, previous)
    record_projection_snapshot(store, window, now, used, reset, display[window]["projected_pct"])
    return _format_projection_pct(display[window]["projected_pct"])


def projection(used_5h, resets_5h, used_7d, resets_7d, now: float, session_id: str = ""):
    try:
        store = load_projection_store()
        p5 = _projection_for_window(store, "five_hour", used_5h, resets_5h, now, session_id)
        p7 = _projection_for_window(store, "seven_day", used_7d, resets_7d, now, session_id)
        save_projection_store(store)
        return p5, p7
    except Exception:
        return "", ""
```

- [ ] **Step 3: Run orchestrator test**

Run:

```bash
PYTHONPATH=src pytest tests/test_projection.py::test_projection_returns_arrow_strings_and_persists_store -q
```

Expected: PASS.

- [ ] **Step 4: Add failing core integration tests**

Create `tests/test_core_projection.py`:

```python
import io
import json
import sys


def test_core_renders_projection_when_enabled(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".claude").mkdir(parents=True)
    (tmp_path / ".claude" / "claude-statusbar.json").write_text(
        json.dumps({
            "show_projection": True,
            "show_forecast": False,
            "show_project_branch": False,
            "show_cache_age": False,
            "show_todos": False,
        }),
        encoding="utf-8",
    )
    import claude_statusbar.predict as predict
    monkeypatch.setattr(predict, "projection", lambda *a, **k: ("→50%", "→90%"))
    payload = json.dumps({
        "session_id": "x",
        "transcript_path": "/n.jsonl",
        "model": {"id": "o", "display_name": "Opus 4.8"},
        "rate_limits": {
            "five_hour": {"used_percentage": 17, "resets_at": 9999999999},
            "seven_day": {"used_percentage": 9, "resets_at": 9999999999},
        },
    })
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    from claude_statusbar.core import main
    main(use_color=False, _suppress_side_effects=True)
    out = capsys.readouterr().out
    assert "→50%" in out
    assert "→90%" in out


def test_core_hides_projection_when_disabled(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".claude").mkdir(parents=True)
    (tmp_path / ".claude" / "claude-statusbar.json").write_text(
        json.dumps({
            "show_projection": False,
            "show_forecast": False,
            "show_project_branch": False,
            "show_cache_age": False,
            "show_todos": False,
        }),
        encoding="utf-8",
    )
    import claude_statusbar.predict as predict
    monkeypatch.setattr(predict, "projection", lambda *a, **k: ("→50%", "→90%"))
    payload = json.dumps({
        "session_id": "x",
        "transcript_path": "/n.jsonl",
        "model": {"id": "o", "display_name": "Opus 4.8"},
        "rate_limits": {
            "five_hour": {"used_percentage": 17, "resets_at": 9999999999},
            "seven_day": {"used_percentage": 9, "resets_at": 9999999999},
        },
    })
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    from claude_statusbar.core import main
    main(use_color=False, _suppress_side_effects=True)
    out = capsys.readouterr().out
    assert "→50%" not in out
    assert "→90%" not in out
```

- [ ] **Step 5: Run core tests and verify they fail**

Run:

```bash
PYTHONPATH=src pytest tests/test_core_projection.py -q
```

Expected: FAIL because `core.main` does not call `projection`.

- [ ] **Step 6: Implement core integration**

In `src/claude_statusbar/core.py`, inside the official rate-limit non-JSON render path before `_render_style(...)`, add:

```python
projection_kwargs = {}
if cfg.show_projection:
    try:
        import time as _t
        from .predict import projection
        p5, p7 = projection(
            used_5h=stdin_data.get("rate_limit_pct"),
            resets_5h=stdin_data.get("rate_limit_resets_at"),
            used_7d=stdin_data.get("rate_limit_7d_pct"),
            resets_7d=stdin_data.get("rate_limit_7d_resets_at"),
            now=_t.time(),
            session_id=stdin_data.get("session_id", ""),
        )
        projection_kwargs = {"projection_5h": p5 or "", "projection_7d": p7 or ""}
    except Exception:
        projection_kwargs = {}
```

Pass `**projection_kwargs` into `_render_style(...)` before `**forecast_kwargs`.

- [ ] **Step 7: Run core tests**

Run:

```bash
PYTHONPATH=src pytest tests/test_core_projection.py tests/test_core_forecast_guard.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/claude_statusbar/predict.py src/claude_statusbar/core.py tests/test_projection.py tests/test_core_projection.py
git commit -m "feat: integrate rate-limit projections"
```

---

### Task 6: Documentation, Compatibility, and Full Verification

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Test: full test suite

- [ ] **Step 1: Update README configuration table**

In `README.md`, add a row near `show_forecast`:

```markdown
| `show_projection` | bool, default `true` | Appends an always-visible `→NN%` projection after each 5h/7d reset timer, estimating the percentage expected at reset. The 5h model blends recent pace, whole-window average, and local baseline; the 7d model integrates learned coarse rhythm buckets (work hours, non-work hours, night, weekend) so a busy first day is not blindly extrapolated across the whole week. Disable with `cs config set show_projection false`. |
```

Update the existing `show_forecast` row so it says it controls only `⚠~ETA`.

- [ ] **Step 2: Update CHANGELOG**

In `CHANGELOG.md`, add under the current unreleased/version section:

```markdown
- **Always-visible rate-limit projections (`show_projection`, default on).**
  The 5h/7d windows now show `→NN%` estimates for expected end-of-window usage.
  The model records local samples, learns coarse usage rhythm, smooths by sample
  time instead of render frequency, and keeps a bounded error log for future
  tuning. `show_forecast` remains the separate `⚠~ETA` warning chip.
```

- [ ] **Step 3: Run targeted tests**

Run:

```bash
PYTHONPATH=src pytest tests/test_projection.py tests/test_forecast_render.py tests/test_config_projection.py tests/test_core_projection.py tests/test_core_forecast_guard.py -q
```

Expected: PASS.

- [ ] **Step 4: Run import performance test**

Run:

```bash
PYTHONPATH=src pytest tests/test_import_perf.py -q
```

Expected: PASS. If it fails because `predict.py` imports new modules eagerly through package import, keep projection imports lazy in `core.main`.

- [ ] **Step 5: Run full test suite**

Run:

```bash
PYTHONPATH=src pytest -q
```

Expected: PASS.

- [ ] **Step 6: Manual smoke check with cached stdin**

Run:

```bash
cat ~/.cache/claude-statusbar/last_stdin.json | PYTHONPATH=src python -m claude_statusbar.cli --no-color
```

Expected: The line contains both projection chips, for example `5h ... →NN%` and `7d ... →NN%`. If `show_forecast` also emits an ETA, projection appears before `⚠~ETA`.

- [ ] **Step 7: Inspect persisted projection store**

Run:

```bash
python - <<'PY'
import json, pathlib
p = pathlib.Path.home() / ".cache" / "claude-statusbar" / "rate_projection.json"
data = json.loads(p.read_text())
print(data.keys())
print(len(data.get("five_hour", [])), len(data.get("seven_day", [])))
print(data.get("display", {}))
PY
```

Expected: keys include `five_hour`, `seven_day`, `display`, `snapshots`, and `closed_windows`; sample counts are nonzero after the smoke check.

- [ ] **Step 8: Commit docs and final verification**

```bash
git add README.md CHANGELOG.md
git commit -m "docs: document rate-limit projections"
```

