# src/claude_statusbar/predict.py
"""Rate-limit forecast — pure and history-free.

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
reset). Needs only the current stdin (used_pct + resets_at) — no sample store,
no concurrency, no warm-up. Stdlib only; lazy-imported on the render path.
Fails safe: odd/insufficient input → None, never raises.
See docs/superpowers/specs/2026-06-02-rate-limit-forecast-design.md."""
from __future__ import annotations

from typing import Optional, Tuple

# Fixed nominal window lengths (seconds). The 5h and 7d limits are plan-level
# constants; resets_at gives the reset instant, so the window started one length
# before it.
WINDOW_LEN_S = {"five_hour": 5 * 3600, "seven_day": 7 * 86400}
# Don't forecast until the window is at least this far along — very early on, a
# couple of percent over a few minutes projects wildly. Sensitivity only (not
# correctness): too-early just defers the chip. Tune empirically.
MIN_ELAPSED_S = {"five_hour": 10 * 60, "seven_day": 60 * 60}

# Debug-mode placeholder shown when the projection can't be computed yet.
DEBUG_PLACEHOLDER = "→--"   # "→--"


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


def forecast_chip(window: str, used_pct, resets_at, now: float,
                  debug: bool = False) -> Optional[str]:
    """Raw chip for one window. Production: `~<eta>` when projected to hit 100%
    before reset, else None. `debug=True` (a temporary validation aid) instead
    surfaces the projected end-of-window % continuously — `→72%`, or `→--` while
    it can't be computed yet — so the model can be eyeballed against real usage."""
    miss = DEBUG_PLACEHOLDER if debug else None
    try:
        used = float(used_pct)
    except (TypeError, ValueError):
        return miss
    if resets_at is None:
        return miss
    try:
        time_to_reset = float(resets_at) - now
    except (TypeError, ValueError):
        return miss
    length = WINDOW_LEN_S.get(window)
    if length is None or time_to_reset <= 0:
        return miss
    elapsed = length - time_to_reset
    if elapsed < MIN_ELAPSED_S.get(window, 0):
        return miss                        # too early in the window to trust
    projected = project_window(used, time_to_reset, length)
    if projected is None:
        return miss
    projected_final, ttl = projected
    if projected_final >= 100:             # on track to exhaust before reset
        return format_eta(ttl)             # at-risk ETA — the production signal
    if debug:
        return f"→{projected_final:.0f}%"   # "→72%" projected end-of-window
    return None


def forecast(used_5h, resets_5h, used_7d, resets_7d, now: float,
             debug: bool = False):
    """Compute (chip_5h, chip_7d). Pure given its args (no I/O). Never raises.
    `debug` forwards to forecast_chip (projected-% always-show validation mode)."""
    try:
        c5 = forecast_chip("five_hour", used_5h, resets_5h, now, debug)
        c7 = forecast_chip("seven_day", used_7d, resets_7d, now, debug)
        return c5, c7
    except Exception:
        return None, None
