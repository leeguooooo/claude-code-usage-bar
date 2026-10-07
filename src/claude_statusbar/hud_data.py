#!/usr/bin/env python3
"""P0 data layer for the desktop HUD.

Official 5h/7d used% + reset countdowns from Claude Desktop's own
plan-usage-history.json (sampled every 5 min; instant read).
"""
import json, time
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List, Dict

PLAN_USAGE = Path.home() / "Library/Application Support/Claude/plan-usage-history.json"
FIVE_H = 5 * 3600
SEVEN_D = 7 * 24 * 3600
DROP = 15
STALE_S = 15 * 60


@dataclass
class Usage:
    fh: Optional[int] = None
    sd: Optional[int] = None
    org: str = ""
    sample_age_s: Optional[float] = None
    fh_reset_s: Optional[float] = None
    sd_reset_s: Optional[float] = None
    stale: bool = False
    err: str = ""


# ---------- usage ----------
def _load_usage() -> List[Dict]:
    d = json.loads(PLAN_USAGE.read_text(encoding="utf-8"))
    return d.get("samples", [])


def _last_reset_ms(samples, key):
    last = None
    for i in range(1, len(samples)):
        a, b = samples[i - 1]["u"].get(key), samples[i]["u"].get(key)
        if a is None or b is None:
            continue
        if a - b >= DROP:
            last = samples[i]["t"]
    return last


def _countdown(samples, key, window_s, now):
    lr = _last_reset_ms(samples, key)
    if lr is None:
        return None
    r = lr / 1000 + window_s - now
    while r < 0:
        r += window_s
    return r


def snapshot(org: Optional[str] = None, now: Optional[float] = None) -> Usage:
    now = time.time() if now is None else now
    try:
        alls = _load_usage()
    except FileNotFoundError:
        return Usage(err="plan-usage-history.json not found")
    except Exception as e:
        return Usage(err=f"read failed: {e}")
    if not alls:
        return Usage(err="no samples")
    cur_org = org or alls[-1].get("org", "")
    s = [e for e in alls if e.get("org") == cur_org]
    last = s[-1]
    age = now - last["t"] / 1000
    return Usage(
        fh=last["u"].get("fh"), sd=last["u"].get("sd"), org=cur_org,
        sample_age_s=age,
        fh_reset_s=_countdown(s, "fh", FIVE_H, now),
        sd_reset_s=_countdown(s, "sd", SEVEN_D, now),
        stale=age > STALE_S,
    )


def fmt_dur(s):
    if s is None:
        return "—"
    s = int(s)
    h, m = s // 3600, (s % 3600) // 60
    if h >= 24:
        return f"{h//24}d{h%24}h"
    return f"{h}h{m:02d}m" if h else f"{m}m"


if __name__ == "__main__":
    u = snapshot()
    print("err:", u.err or "(none)")
    print(f"5h: {u.fh}%  reset {fmt_dur(u.fh_reset_s)}   |   7d: {u.sd}%  reset {fmt_dur(u.sd_reset_s)}")
