# src/claude_statusbar/predict.py
"""Rate-limit burn-rate forecast — pure helpers + a tiny account-global sample
store. Stdlib only; lazy-imported on the render path (kept off the banned
import graph). Everything fails safe: insufficient/odd input → None, never raise.
See docs/superpowers/specs/2026-06-02-rate-limit-forecast-design.md."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List, Optional, Tuple

Sample = Tuple[float, float]  # (unix_ts, used_pct)

# Provisional, tune empirically (sensitivity only, not correctness):
LOOKBACK_S = {"five_hour": 30 * 60, "seven_day": 2 * 3600}
# Minimum observation span before a rate is trusted. A burst measured over a few
# seconds must NOT be extrapolated to a multi-hour/day horizon — that's what made
# a 60s 6%→7% tick on the 7d window forecast "~20m to limit". Require samples to
# span at least this long; until then, stay silent (fail-safe direction).
MIN_OBS_SPAN_S = {"five_hour": 5 * 60, "seven_day": 30 * 60}
# Minimum wall-clock gap between recorded samples. The store is account-global
# and, in daemon mode, every active session writes it each tick — without a
# throttle that packed 200 samples into <1 min, so the series never spanned the
# min-observation window and the chip was stuck on "~--". One sample / 30s keeps
# 200 samples spanning ~100 min, comfortably beyond both MIN_OBS_SPAN_S floors.
REC_GAP_S = 30
_MAX_SAMPLES = 200          # hard cap per series so the file stays tiny


def format_eta(seconds: float) -> str:
    """Compact `~30s` / `~40m` / `~2h10m`. Minutes band floors seconds away."""
    s = int(seconds)
    if s < 60:
        return f"~{s}s"
    if s < 3600:
        return f"~{s // 60}m"
    return f"~{s // 3600}h{(s % 3600) // 60:02d}m"


def burn_rate(samples: List[Sample], now: float, lookback_s: float,
              min_span_s: float = 0) -> Optional[float]:
    """Recent burn in percent/second over samples within `lookback_s` of `now`.
    None when <2 in-window samples, Δt ≤ 0, the rate is ≤ 0 (plateau/dip —
    e.g. rolling-window ageing-out: fail safe, show nothing), or the samples
    span less than `min_span_s` (too little observation to extrapolate)."""
    # Tolerate a hand-corrupted store: keep only well-formed [ts, pct] pairs
    # so a malformed element never raises (fail-safe contract → None, not crash).
    recent = [
        (s[0], s[1]) for s in samples
        if isinstance(s, (list, tuple)) and len(s) == 2 and 0 <= now - s[0] <= lookback_s
    ]
    if len(recent) < 2:
        return None
    recent.sort()
    (t0, p0), (t1, p1) = recent[0], recent[-1]
    dt = t1 - t0
    dp = p1 - p0
    if dt <= 0 or dp <= 0 or dt < min_span_s:
        return None
    return dp / dt


def time_to_limit(used_pct: float, rate: Optional[float]) -> Optional[float]:
    """Seconds to reach 100% at `rate` (%/s). None if not burning or already full."""
    if rate is None or rate <= 0 or used_pct >= 100:
        return None
    return (100.0 - used_pct) / rate


_HISTORY_PATH = Path(os.path.expanduser("~")) / ".cache" / "claude-statusbar" / "rate_history.json"


def load_history(path: Optional[Path] = None) -> dict:
    """Read the global sample store; {} on missing/corrupt/unreadable.
    Resolve the default at CALL time (not a def-time default) so tests can
    monkeypatch `predict._HISTORY_PATH`."""
    path = Path(path) if path is not None else _HISTORY_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def record_sample(history: dict, window: str, pct: float, now: float,
                  min_gap_s: float = 0) -> dict:
    """Append (now, pct) for `window` ONLY when pct changed from the last sample
    (used_pct is a step function) AND at least `min_gap_s` has elapsed since the
    last recorded sample (throttle — many sessions write this shared store each
    daemon tick). Then prune to _MAX_SAMPLES. Returns history (mutated in place +
    returned for chaining). Caller persists via save_history."""
    try:
        pct = float(pct)
    except (TypeError, ValueError):
        return history
    series = history.get(window)
    if not isinstance(series, list):
        series = []
        history[window] = series
    last = series[-1] if series else None
    if isinstance(last, (list, tuple)) and len(last) == 2:
        if last[1] == pct:
            return history  # dedup unchanged pct
        if min_gap_s and 0 <= now - last[0] < min_gap_s:
            return history  # throttle: too soon since the last recorded sample
    series.append([float(now), pct])
    if len(series) > _MAX_SAMPLES:
        del series[: len(series) - _MAX_SAMPLES]
    return history


def save_history(history: dict, path: Optional[Path] = None) -> None:
    """Atomic write (tmp + os.replace) — concurrent windows can't corrupt it.
    Default resolved at call time (see load_history) so it's monkeypatchable."""
    path = Path(path) if path is not None else _HISTORY_PATH
    from .cache import atomic_write_text
    try:
        atomic_write_text(path, json.dumps(history))
    except OSError:
        pass


DEBUG_PLACEHOLDER = "~--"   # shown in debug mode while the rate is still warming up


def forecast_chip(history: dict, window: str, used_pct, resets_at,
                  now: float, debug: bool = False) -> Optional[str]:
    """Raw `~<eta>` chip string when this window is projected to hit 100% before
    it resets, else None. Pure given `history` (does NOT record/persist).

    `debug=True` is a temporary validation aid: surface the estimate continuously
    even when it's *not* at-risk (so the burn-rate model can be eyeballed against
    real usage), and a `~--` placeholder while the rate is still warming up. The
    min-span guard still applies, so debug shows the real shipping behaviour."""
    try:
        used = float(used_pct)
    except (TypeError, ValueError):
        return DEBUG_PLACEHOLDER if debug else None
    if resets_at is None:
        return DEBUG_PLACEHOLDER if debug else None
    try:
        time_to_reset = float(resets_at) - now
    except (TypeError, ValueError):
        return DEBUG_PLACEHOLDER if debug else None
    if time_to_reset <= 0:
        return DEBUG_PLACEHOLDER if debug else None
    rate = burn_rate(history.get(window, []), now, LOOKBACK_S.get(window, 1800),
                     MIN_OBS_SPAN_S.get(window, 0))
    ttl = time_to_limit(used, rate)
    if ttl is not None and ttl < time_to_reset:
        return format_eta(ttl)          # at-risk — the production signal
    if debug:
        # Not at-risk: show the estimate anyway (safe but computable) or a
        # placeholder (no trustworthy rate yet).
        return format_eta(ttl) if ttl is not None else DEBUG_PLACEHOLDER
    return None


def forecast(used_5h, resets_5h, used_7d, resets_7d, now: float, debug: bool = False):
    """Record both windows' current samples, persist once, and return
    (chip_5h, chip_7d). One read + at-most-one write per render. Never raises.
    `debug` forwards to forecast_chip (always-show validation mode)."""
    try:
        history = load_history()
        if used_5h is not None:
            record_sample(history, "five_hour", used_5h, now, REC_GAP_S)
        if used_7d is not None:
            record_sample(history, "seven_day", used_7d, now, REC_GAP_S)
        save_history(history)
        c5 = forecast_chip(history, "five_hour", used_5h, resets_5h, now, debug)
        c7 = forecast_chip(history, "seven_day", used_7d, resets_7d, now, debug)
        return c5, c7
    except Exception:
        return None, None
