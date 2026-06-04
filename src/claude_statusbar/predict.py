# src/claude_statusbar/predict.py
"""Rate-limit forecast and end-of-window projection.

Projects each window's end-of-window usage from the AVERAGE pace *so far this
window*, not a noisy recent burst. A burst-rate extrapolation gets whipsawed by
the first few seconds of activity (and used_pct is a coarse integer step), so it
produced absurd ETAs ("~20m to the 7-day limit" off a 60s tick). The average
pace over the whole elapsed window is stable and self-correcting: idle time is
averaged in, so it answers the honest question "at the rate you've actually been
going this window, where will you end up — and will you hit the cap first?"

`resets_at` marks when the window resets; the window has been accumulating since
`resets_at - WINDOW_LEN_S`, so:

    elapsed   = window_len - time_to_reset
    avg_rate  = used_pct / elapsed                  # %/s over the window so far
    projected = used_pct + avg_rate * time_to_reset # == used * window_len / elapsed
    ttl       = (100 - used_pct) / avg_rate         # secs to 100% at that pace

Show an at-risk `~ETA` chip when `projected >= 100` (on track to exhaust before
reset). The separate always-visible `→NN%` projection keeps a small bounded
history to learn local work/off-hour bucket rates over time. Stdlib only;
lazy-imported on the render path. Fails safe: odd/insufficient input → None,
never raises.
See docs/superpowers/specs/2026-06-02-rate-limit-forecast-design.md."""
from __future__ import annotations

import json
import math
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Fixed nominal window lengths (seconds). The 5h and 7d limits are plan-level
# constants; resets_at gives the reset instant, so the window started one length
# before it.
WINDOW_LEN_S = {"five_hour": 5 * 3600, "seven_day": 7 * 86400}
# Don't forecast until the window is at least this far along — very early on, a
# couple of percent over a few minutes projects wildly. Sensitivity only (not
# correctness): too-early just defers the chip. Tune empirically.
MIN_ELAPSED_S = {"five_hour": 10 * 60, "seven_day": 60 * 60}

# A countdown only helps when the wall is genuinely near. Beyond this, a
# projected `~137h` ETA is noise — show the projected % instead (colour carries
# the urgency). So `⚠<eta>` appears only when ≤ this many seconds to the cap.
IMMINENT_ETA_S = 60 * 60

# Placeholder shown when the projection can't be computed yet (too early / no
# usage / odd input).
DEBUG_PLACEHOLDER = "→--"   # "→--"

# Shared "latest account reading" store. The 5h/7d quota is account-global, but
# each Claude Code window only sees the used_pct that Claude last pushed into ITS
# stdin (Claude refreshes that field per-session on its own cadence, not every
# second), so different windows hold different used_pct and disagree. Every
# window re-renders ~1×/s, so a single tiny shared record that each render
# reconciles against makes all windows converge to the freshest reading within a
# tick. ONE record per window, overwrite-on-newer (not an append log) → trivial
# last-writer-wins concurrency, no write storm.
_LATEST_PATH = Path(os.path.expanduser("~")) / ".cache" / "claude-statusbar" / "rate_latest.json"

MAX_PROJECTION_SAMPLES = 5000
MAX_PROJECTION_SNAPSHOTS = 1000
MAX_CLOSED_WINDOWS = 100
_PROJECTION_PATH = Path(os.path.expanduser("~")) / ".cache" / "claude-statusbar" / "rate_projection.json"
PROJECTION_RESULT_TTL_S = 1.0
_PROJECTION_RESULT_CACHE: Optional[Dict[str, Any]] = None

DEFAULT_BUCKET_PRIORS = {
    "night": 0.02,
    "weekday_work_hours": 0.45,
    "weekday_non_work_hours": 0.12,
    "weekend": 0.10,
}
LEARNED_BUCKET_FULL_WEIGHT_SAMPLES = 20
TAU_SECONDS = {"five_hour": 8 * 60, "seven_day": 2 * 3600}


def format_eta(seconds: float) -> str:
    """Compact `~30s` / `~40m` / `~2h10m`. Minutes band floors seconds away."""
    s = int(seconds)
    if s < 60:
        return f"~{s}s"
    if s < 3600:
        return f"~{s // 60}m"
    return f"~{s // 3600}h{(s % 3600) // 60:02d}m"


def project_window(used_pct, time_to_reset: float,
                   window_len: float) -> Optional[Tuple[float, float]]:
    """Return (projected_final_pct, seconds_to_100) at the window's average pace
    so far, or None if it can't be computed (bad input, before the window
    started, no usage, or already capped). Pure arithmetic — no I/O, no clock."""
    try:
        used = float(used_pct)
        ttr = float(time_to_reset)
        length = float(window_len)
    except (TypeError, ValueError):
        return None
    if ttr <= 0 or length <= 0 or used <= 0 or used >= 100:
        return None
    elapsed = length - ttr
    if elapsed <= 0:                       # reset further out than a full window
        return None
    avg_rate = used / elapsed              # %/s averaged over the window so far
    projected_final = used + avg_rate * ttr
    ttl = (100.0 - used) / avg_rate
    return projected_final, ttl


def forecast_chip(window: str, used_pct, resets_at, now: float) -> Optional[str]:
    """Raw ETA chip for one window. Returns `~<eta>` only when the window is
    projected to hit 100% within the imminent ETA band before reset. Otherwise
    returns None. End-of-window `→NN%` projections are handled by projection()."""
    try:
        used = float(used_pct)
    except (TypeError, ValueError):
        return None
    if resets_at is None:
        return None
    try:
        time_to_reset = float(resets_at) - now
    except (TypeError, ValueError):
        return None
    length = WINDOW_LEN_S.get(window)
    if length is None or time_to_reset <= 0:
        return None
    elapsed = length - time_to_reset
    if elapsed < MIN_ELAPSED_S.get(window, 0):
        return None                        # too early in the window to trust
    projected = project_window(used, time_to_reset, length)
    if projected is None:
        return None
    projected_final, ttl = projected
    if projected_final >= 100 and ttl <= IMMINENT_ETA_S:
        return format_eta(ttl)             # ⚠ imminent — show the countdown
    return None


def _coerce(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _is_newer(cur_used, cur_reset, prev_used, prev_reset) -> bool:
    """Is (cur_used, cur_reset) a fresher account reading than (prev_used,
    prev_reset)? Within a window used_pct only grows, and a new window has a
    later resets_at — so 'newer' = later reset, or same reset with higher used."""
    if prev_used is None or prev_reset is None:
        return True
    if cur_reset > prev_reset:
        return True
    return cur_reset == prev_reset and cur_used > prev_used


def reconcile_account(used_5h, resets_5h, used_7d, resets_7d, path=None):
    """Merge this window's per-session reading into the shared account-global
    store and return the freshest (u5, r5, u7, r7). Makes every window converge
    to the same numbers within one render tick. Never raises — on any I/O error
    it just returns the inputs (degrades to per-session behaviour)."""
    p = Path(path) if path is not None else _LATEST_PATH
    try:
        try:
            store = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(store, dict):
                store = {}
        except (OSError, json.JSONDecodeError, ValueError):
            store = {}

        out = {}
        changed = False
        for win, used, reset in (("five_hour", used_5h, resets_5h),
                                 ("seven_day", used_7d, resets_7d)):
            prev = store.get(win) if isinstance(store.get(win), dict) else {}
            pu, pr = _coerce(prev.get("used")), _coerce(prev.get("resets_at"))
            cu, cr = _coerce(used), _coerce(reset)
            if cu is not None and cr is not None and _is_newer(cu, cr, pu, pr):
                store[win] = {"used": cu, "resets_at": cr}
                out[win] = (cu, cr)
                changed = True
            else:
                out[win] = (pu if pu is not None else cu,
                            pr if pr is not None else cr)

        if changed:
            from .cache import atomic_write_text
            try:
                atomic_write_text(p, json.dumps(store))
            except OSError:
                pass
        return out["five_hour"][0], out["five_hour"][1], out["seven_day"][0], out["seven_day"][1]
    except Exception:
        return used_5h, resets_5h, used_7d, resets_7d


def forecast(used_5h, resets_5h, used_7d, resets_7d, now: float):
    """Compute (chip_5h, chip_7d). Reconciles against the shared account-global
    latest reading first (so all windows agree), then projects. Never raises."""
    try:
        u5, r5, u7, r7 = reconcile_account(used_5h, resets_5h, used_7d, resets_7d)
        c5 = forecast_chip("five_hour", u5, r5, now)
        c7 = forecast_chip("seven_day", u7, r7, now)
        return c5, c7
    except Exception:
        return None, None


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
    for key in store:
        if key in data:
            store[key] = data[key]
    for key in ("five_hour", "seven_day", "snapshots", "closed_windows"):
        if not isinstance(store.get(key), list):
            store[key] = []
    if not isinstance(store.get("display"), dict):
        store["display"] = {}
    for window in ("five_hour", "seven_day"):
        store[window] = _compressed_samples(store[window], window)[-MAX_PROJECTION_SAMPLES:]
    store["snapshots"] = store["snapshots"][-MAX_PROJECTION_SNAPSHOTS:]
    store["closed_windows"] = store["closed_windows"][-MAX_CLOSED_WINDOWS:]
    store["version"] = 1
    return store


def save_projection_store(store: Dict[str, Any], path=None) -> None:
    p = Path(path) if path is not None else _PROJECTION_PATH
    from .cache import atomic_write_text
    atomic_write_text(p, json.dumps(store, separators=(",", ":")))


def _valid_window(window: str) -> bool:
    return window in WINDOW_LEN_S


def _sample_numbers(sample: Dict[str, Any]) -> Optional[Tuple[float, float, float]]:
    try:
        ts = float(sample["observed_at"])
        used = float(sample["used_pct"])
        reset = float(sample["resets_at"])
    except (KeyError, TypeError, ValueError):
        return None
    if ts <= 0 or reset <= 0 or used < 0:
        return None
    return ts, max(0.0, min(100.0, used)), reset


def _plausible_reset(window: str, observed_at: float, resets_at: float) -> bool:
    length = WINDOW_LEN_S.get(window)
    if length is None:
        return False
    # Claude can refresh slightly late, and tests use simple synthetic epochs.
    # Anything much farther than the nominal window is stale/polluted history.
    return resets_at >= observed_at - 60.0 and resets_at <= observed_at + length + 86400.0


def _compressed_samples(samples: List[Dict[str, Any]], window: Optional[str] = None) -> List[Dict[str, float]]:
    grouped: Dict[float, List[Tuple[float, float, float]]] = {}
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        vals = _sample_numbers(sample)
        if vals is None:
            continue
        ts, used, reset = vals
        if window is not None and not _plausible_reset(window, ts, reset):
            continue
        grouped.setdefault(reset, []).append((ts, used, reset))

    out: List[Dict[str, float]] = []
    for reset, rows in grouped.items():
        last_used: Optional[float] = None
        for ts, used, _reset in sorted(rows, key=lambda r: r[0]):
            if last_used is not None and used <= last_used:
                continue
            out.append({"observed_at": ts, "used_pct": used, "resets_at": reset})
            last_used = used
    out.sort(key=lambda s: s["observed_at"])
    return out


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
    if not _plausible_reset(window, ts, reset):
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
    valid_existing = _compressed_samples(series, window)
    if valid_existing:
        latest_reset = max(float(s["resets_at"]) for s in valid_existing)
        if reset < latest_reset:
            return store
        if reset == latest_reset:
            max_used = max(float(s["used_pct"]) for s in valid_existing if float(s["resets_at"]) == reset)
            if sample["used_pct"] <= max_used:
                return store
    if series and series[-1] == sample:
        return store
    series.append(sample)
    series.sort(key=lambda s: float(s.get("observed_at", 0.0)))
    del series[:-MAX_PROJECTION_SAMPLES]
    return store


def _local_datetime(ts: float) -> datetime:
    return datetime.fromtimestamp(float(ts))


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
    ordered = _compressed_samples(samples)
    for prev, cur in zip(ordered, ordered[1:]):
        try:
            dt = float(cur["observed_at"]) - float(prev["observed_at"])
            du = float(cur["used_pct"]) - float(prev["used_pct"])
            prev_reset = float(prev["resets_at"])
            cur_reset = float(cur["resets_at"])
        except (KeyError, TypeError, ValueError):
            continue
        if cur_reset != prev_reset:
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
        agg["rate_per_hour"] = (
            agg["total_rate"] / samples_n
            if samples_n else DEFAULT_BUCKET_PRIORS.get(bucket, 0.0)
        )
    return out


def expected_bucket_rate(bucket: str, learned: Optional[Dict[str, float]] = None) -> float:
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


def _samples_for_reset(samples: List[Dict[str, Any]], resets_at: float) -> List[Dict[str, Any]]:
    return [s for s in samples if _coerce(s.get("resets_at")) == float(resets_at)]


def _rate_from_samples(samples: List[Dict[str, Any]], now: float, lookback_s: float) -> Optional[float]:
    cutoff = now - lookback_s
    ordered = _compressed_samples(samples)
    in_window = [
        s for s in ordered
        if float(s.get("observed_at", 0.0)) >= cutoff
        and float(s.get("observed_at", 0.0)) <= now
    ]
    if len(in_window) < 2:
        return None
    first, last = in_window[0], in_window[-1]
    try:
        dt = float(last["observed_at"]) - float(first["observed_at"])
        du = float(last["used_pct"]) - float(first["used_pct"])
    except (KeyError, TypeError, ValueError):
        return None
    if dt <= 0 or du <= 0:
        return None
    rate = du / dt
    if rate > 20.0 / 3600.0:
        return None
    return rate


def project_5h(current_used: float, resets_at: float, now: float,
               samples: List[Dict[str, Any]]) -> float:
    used = float(current_used)
    ttr = max(0.0, float(resets_at) - float(now))
    window_avg = project_window(used, ttr, WINDOW_LEN_S["five_hour"])
    avg_rate = None
    if window_avg is not None and ttr > 0:
        projected_final, _ttl = window_avg
        avg_rate = max(0.0, (projected_final - used) / ttr)
    recent = _rate_from_samples(samples, float(now), 3600.0)
    learned = learn_bucket_rates(samples)
    bucket = bucket_for_time(now)
    bucket_rate = expected_bucket_rate(bucket, learned.get(bucket, {})) / 3600.0
    rates = []
    weights = []
    if recent is not None:
        rates.append(recent)
        weights.append(0.55)
    if avg_rate is not None:
        rates.append(avg_rate)
        weights.append(0.30 if recent is not None else 0.75)
    rates.append(bucket_rate)
    weights.append(0.15 if recent is not None else 0.25)
    total_w = sum(weights)
    blended = sum(r * w for r, w in zip(rates, weights)) / total_w if total_w else 0.0
    return max(used, min(100.0, used + blended * ttr))


def project_7d(current_used: float, resets_at: float, now: float,
               samples: List[Dict[str, Any]]) -> float:
    used = float(current_used)
    learned = learn_bucket_rates(samples)
    future = integrate_future_buckets(float(now), float(resets_at), learned)
    ttr = max(0.0, float(resets_at) - float(now))
    window_avg = project_window(used, ttr, WINDOW_LEN_S["seven_day"])
    sanity = 0.0
    if window_avg is not None:
        sanity = max(0.0, window_avg[0] - used) * 0.10
    return max(used, min(100.0, used + future + sanity))


def smooth_projection(window: str, raw: float, current_used: float,
                      observed_at: float, previous: Optional[Dict[str, Any]] = None) -> Dict[str, float]:
    raw = max(float(current_used), min(100.0, float(raw)))
    ts = float(observed_at)
    if not previous:
        return {"projected_pct": raw, "updated_at": ts}
    prev_ts = _coerce(previous.get("updated_at"))
    prev_pct = _coerce(previous.get("projected_pct"))
    if prev_ts is None or prev_pct is None:
        return {"projected_pct": raw, "updated_at": ts}
    if ts <= prev_ts:
        return {"projected_pct": max(float(current_used), min(100.0, prev_pct)),
                "updated_at": prev_ts}
    tau = TAU_SECONDS.get(window, 900)
    alpha = 1.0 - math.exp(-(ts - prev_ts) / tau)
    smoothed = prev_pct * (1.0 - alpha) + raw * alpha
    return {"projected_pct": max(float(current_used), min(100.0, smoothed)),
            "updated_at": ts}


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
    if not isinstance(snaps, list):
        snaps = []
        store["snapshots"] = snaps
    snaps.append(snap)
    del snaps[:-MAX_PROJECTION_SNAPSHOTS]
    return store


def close_changed_windows(store: Dict[str, Any], window: str) -> Dict[str, Any]:
    series = store.get(window, [])
    if not isinstance(series, list) or len(series) < 2:
        return store
    closed = store.setdefault("closed_windows", [])
    if not isinstance(closed, list):
        closed = []
        store["closed_windows"] = closed
    seen = {
        (c.get("window"), c.get("previous_resets_at"))
        for c in closed if isinstance(c, dict)
    }
    ordered = sorted(
        (s for s in series if isinstance(s, dict)),
        key=lambda s: float(s.get("observed_at", 0.0)),
    )
    for prev, cur in zip(ordered, ordered[1:]):
        prev_vals = _sample_numbers(prev)
        cur_vals = _sample_numbers(cur)
        if prev_vals is None or cur_vals is None:
            continue
        _prev_ts, prev_used, prev_reset = prev_vals
        cur_ts, _cur_used, cur_reset = cur_vals
        if cur_reset > prev_reset and (window, prev_reset) not in seen:
            closed.append({
                "window": window,
                "previous_resets_at": prev_reset,
                "actual_final_pct": prev_used,
                "closed_at": cur_ts,
            })
            seen.add((window, prev_reset))
    del closed[:-MAX_CLOSED_WINDOWS]
    return store


def _format_projection_pct(value: float) -> str:
    return f"→{max(0.0, min(100.0, float(value))):.0f}%"


def _projection_result_key(u5, r5, u7, r7) -> Optional[Tuple[str, str, float, float, float, float]]:
    try:
        return (
            str(_PROJECTION_PATH),
            str(_LATEST_PATH),
            float(u5),
            float(r5),
            float(u7),
            float(r7),
        )
    except (TypeError, ValueError):
        return None


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
    raw = (
        project_5h(used, reset, now, samples)
        if window == "five_hour"
        else project_7d(used, reset, now, samples)
    )
    display = store.setdefault("display", {})
    previous = display.get(window) if isinstance(display.get(window), dict) else None
    if previous is not None and _coerce(previous.get("resets_at")) != reset:
        previous = None
    display[window] = smooth_projection(window, raw, used, now, previous)
    display[window]["resets_at"] = reset
    record_projection_snapshot(store, window, now, used, reset, display[window]["projected_pct"])
    return _format_projection_pct(display[window]["projected_pct"])


def projection(used_5h, resets_5h, used_7d, resets_7d, now: float, session_id: str = ""):
    try:
        u5, r5, u7, r7 = reconcile_account(used_5h, resets_5h, used_7d, resets_7d)
        ts = float(now)
        key = _projection_result_key(u5, r5, u7, r7)
        global _PROJECTION_RESULT_CACHE
        if key is not None and isinstance(_PROJECTION_RESULT_CACHE, dict):
            cached_at = _coerce(_PROJECTION_RESULT_CACHE.get("observed_at"))
            if (
                _PROJECTION_RESULT_CACHE.get("key") == key
                and cached_at is not None
                and 0.0 <= ts - cached_at <= PROJECTION_RESULT_TTL_S
            ):
                result = _PROJECTION_RESULT_CACHE.get("result")
                if isinstance(result, tuple) and len(result) == 2:
                    return result
        store = load_projection_store()
        p5 = _projection_for_window(store, "five_hour", u5, r5, now, session_id)
        p7 = _projection_for_window(store, "seven_day", u7, r7, now, session_id)
        save_projection_store(store)
        result = (p5, p7)
        if key is not None:
            _PROJECTION_RESULT_CACHE = {
                "key": key,
                "observed_at": ts,
                "result": result,
            }
        return result
    except Exception:
        return "", ""
