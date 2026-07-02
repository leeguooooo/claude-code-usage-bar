#!/usr/bin/env python3
"""Offline backtest for the →NN% projection against real usage history.

Replays project_5h over every closed 5h window recorded in the account's
rate_projection store, comparing what WOULD have been predicted at each
historical sample against the window's actual final usage. This is the
harness that exposed the 2026-07-02 Simpson's paradox (global overestimate
driven by idle windows masking a mid-window UNDERestimate in heavy windows)
— run it before and after any projection tuning.

Usage:
    python tools/backtest.py                     # default account store
    python tools/backtest.py path/to/rate_projection.json
    python tools/backtest.py --since 2026-06-25  # windows resetting after date

Ground truth: closed_windows.actual_final_pct when recorded, else the max
sampled pct (only for windows whose samples span ≥50% of the window —
sparse windows are dropped, their "final" would be a lower bound).
"""
import argparse
import datetime
import glob
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from claude_statusbar.predict import project_5h  # noqa: E402

WINDOW_S = 5 * 3600


def default_store() -> str:
    root = os.path.expanduser("~/.cache/claude-statusbar")
    keyed = sorted(glob.glob(os.path.join(root, "rate_projection.*.json")),
                   key=os.path.getmtime, reverse=True)
    return keyed[0] if keyed else os.path.join(root, "rate_projection.json")


def collect_points(store: dict, since_ts: float):
    finals = {c["previous_resets_at"]: c["actual_final_pct"]
              for c in store.get("closed_windows", [])
              if c.get("window") == "five_hour"}
    by_reset = defaultdict(list)
    for s in store.get("five_hour", []):
        by_reset[s["resets_at"]].append(s)
    pts, skipped = [], 0
    for reset, samples in by_reset.items():
        if reset < since_ts:
            continue
        samples.sort(key=lambda x: x["observed_at"])
        closed = reset in finals
        span = (samples[-1]["observed_at"] - samples[0]["observed_at"]) / WINDOW_S
        if len(samples) < 4 or (not closed and span < 0.5):
            skipped += 1
            continue
        final = finals.get(reset, max(x["used_pct"] for x in samples))
        for i in range(2, len(samples)):
            t = samples[i]["observed_at"]
            used = samples[i]["used_pct"]
            progress = 1 - (reset - t) / WINDOW_S
            if not (0 <= progress <= 1):
                continue
            predicted = project_5h(used, reset, t, samples[:i + 1])
            burning = any(t - x["observed_at"] <= 900 and x["used_pct"] < used
                          for x in samples[:i])
            pts.append({"reset": reset, "progress": progress, "used": used,
                        "predicted": predicted, "final": final,
                        "burning": burning})
    return pts, skipped


def report(rows, label):
    if len(rows) < 15:
        print(f"-- {label}: n={len(rows)} (too few, skipped)")
        return
    errs = sorted(r["predicted"] - r["final"] for r in rows)
    n = len(errs)
    mae = sum(abs(e) for e in errs) / n
    p90 = sorted(abs(e) for e in errs)[int(n * 0.9)]
    under = sum(1 for e in errs if e < -10) / n * 100
    over = sum(1 for e in errs if e > 10) / n * 100
    print(f"-- {label} (n={n})")
    print(f"   median={errs[n // 2]:+6.1f}  MAE={mae:5.1f}  P90|err|={p90:5.1f}"
          f"  低估>10pp={under:3.0f}%  高估>10pp={over:3.0f}%")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("store", nargs="?", default=default_store())
    ap.add_argument("--since", default=None,
                    help="only windows resetting on/after YYYY-MM-DD")
    args = ap.parse_args()
    since_ts = 0.0
    if args.since:
        since_ts = datetime.datetime.strptime(args.since, "%Y-%m-%d").timestamp()

    store = json.load(open(args.store))
    pts, skipped = collect_points(store, since_ts)
    windows = len({r["reset"] for r in pts})
    print(f"store: {args.store}")
    print(f"回测 {windows} 个 5h 窗口, {len(pts)} 个预测时点"
          f" (剔除 {skipped} 个真值不可靠的稀疏窗口)\n")

    print("== 按窗口进度 ==")
    for b in range(5):
        report([r for r in pts if min(int(r["progress"] * 5), 4) == b],
               f"进度 {b * 20:3d}-{b * 20 + 20}%")
    print("\n== 按窗口最终用量(全部进度)==")
    for lo, hi, tag in ((0, 20, "清淡 F<20%"), (20, 40, "中等 20≤F<40"),
                        (40, 101, "重度 F≥40%")):
        report([r for r in pts if lo <= r["final"] < hi], tag)
    print("\n== 重度窗口 × 燃烧中(用户盯着条的时刻)==")
    for b in range(5):
        report([r for r in pts if r["final"] >= 40 and r["burning"]
                and min(int(r["progress"] * 5), 4) == b],
               f"F≥40 燃烧中 进度 {b * 20}-{b * 20 + 20}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
