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
_MAX_SAMPLES = 200          # hard cap per series so the file stays tiny
URGENT_ETA_S = 10 * 60      # ≤ this → "hot" color (decided in the renderer)


def format_eta(seconds: float) -> str:
    """Compact `~30s` / `~40m` / `~2h10m`. Minutes band floors seconds away."""
    s = int(seconds)
    if s < 60:
        return f"~{s}s"
    if s < 3600:
        return f"~{s // 60}m"
    return f"~{s // 3600}h{(s % 3600) // 60:02d}m"


def burn_rate(samples: List[Sample], now: float, lookback_s: float) -> Optional[float]:
    """Recent burn in percent/second over samples within `lookback_s` of `now`.
    None when <2 in-window samples, Δt ≤ 0, or the rate is ≤ 0 (plateau/dip —
    e.g. rolling-window ageing-out: fail safe, show nothing)."""
    recent = [(t, p) for (t, p) in samples if 0 <= now - t <= lookback_s]
    if len(recent) < 2:
        return None
    recent.sort()
    (t0, p0), (t1, p1) = recent[0], recent[-1]
    dt = t1 - t0
    dp = p1 - p0
    if dt <= 0 or dp <= 0:
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


def record_sample(history: dict, window: str, pct: float, now: float) -> dict:
    """Append (now, pct) for `window` ONLY when pct changed from the last sample
    (used_pct is a step function), then prune to _MAX_SAMPLES. Returns history
    (mutated in place + returned for chaining). Caller persists via save_history."""
    try:
        pct = float(pct)
    except (TypeError, ValueError):
        return history
    series = history.get(window)
    if not isinstance(series, list):
        series = []
        history[window] = series
    if series and series[-1][1] == pct:
        return history  # dedup unchanged pct
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
