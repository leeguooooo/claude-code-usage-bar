# Rate-limit forecast chip — design

**Date:** 2026-06-02
**Status:** approved (pending spec review)
**Scope:** on-bar prediction only. Desktop notifications are a separate, later sub-project.

## Goal

Turn the passive 5h/7d quota gauges into a forecast that answers the user's #1
anxiety — "am I about to run out?" — by showing, **only when it matters**, an
estimated time-to-limit at the *current* burn rate.

## Behaviour

For each rate-limit window (`five_hour`, `seven_day`), when the projected
time-to-100% (at the recent burn rate) is **less than the time until the window
resets**, render a warning chip immediately after that window's `⏰<reset>`
timer:

```
5h[███27%░░░░]⏰1h28m ⚠~40m | 7d[███61%░░░░]⏰5d18h
```

- The chip is `⚠~<duration>` where `<duration>` is the compact time-to-100%
  (`~40m`, `~2h10m`, `~30s`).
- Colour: `s_hot` (red) when the time-to-limit is very short (≤ a small
  threshold, e.g. 10 min), otherwise `s_warn` (yellow).
- When the window is **not** projected to exhaust before it resets (the common
  healthy case), nothing is shown — the feature is silent until it has something
  actionable to say.
- The battery bar, the `%`, and the `⏰<reset>` timer are **unchanged**; the chip
  is purely additive.

**Config:** `show_forecast` (bool). **Default ON.** It is silent until at-risk,
so default-on adds no visible clutter for healthy users; the cost is a small
per-render history read (+ an occasional write). `cs config set show_forecast false`
to disable.

**Style coverage:** classic first (the user's style). Capsule/hairline may get
the chip later; out of scope here unless trivial.

## Model assumptions & safe degradation (the foundation — read first)

The forecast is an **estimate**, not a guarantee — hence the `~`. It assumes the
window behaves as near-monotonic growth toward the cap until `resets_at` (how
Claude's 5h/7d limits are commonly described: a window that resets at a known
time). If the windows are in fact **rolling** (old usage ages out, so
`used_percentage` can plateau or dip even under sustained use), the model
**degrades safely rather than misleads**:

- Plateau / steady-state (rolling equilibrium) → `Δpct ≈ 0` → `rate ≤ 0` →
  **no chip**. Correct: you're not on track to exhaust.
- Actively climbing toward the cap faster than the window resets → a chip with
  an `~`-estimate. This is exactly the at-risk signal, and the only failure is
  being **over-conservative** (warning slightly early because some usage will
  expire), never falsely-reassuring.

So the worst case is "no chip" or "a slightly early warning", never a wrong
green light. Exact window semantics (fixed vs rolling) and the lookback windows
are to be confirmed **empirically** after first ship — they only tune
sensitivity, not correctness of the fail-safe behaviour.

## Architecture

New module `src/claude_statusbar/predict.py` — pure functions plus one light
global sample store. No heavy imports (stays off the banned-import hot path;
`json`, `time`, stdlib only).

### Sample store (account-global)

The 5h/7d quotas are **account-level**, shared across every Claude Code window,
so samples live in ONE global file, not per-session:

`~/.cache/claude-statusbar/rate_history.json` (respects `CLAUDE_CONFIG_DIR`/HOME
the same way other cache paths do):

```json
{
  "five_hour":  [[<unix_ts>, <used_pct>], ...],
  "seven_day":  [[<unix_ts>, <used_pct>], ...]
}
```

- Pruned to a bounded recency window per series (see lookback constants) and a
  hard max sample count, so the file stays tiny.
- Written atomically via `cache.atomic_write_text` (tmp + `os.replace`).

**Why a separate file (not reuse `last_stdin.json`):** `last_stdin.json` is a
single *snapshot* (the latest payload); burn rate needs a *time series* of past
`used_pct`, which the snapshot can't provide. `rate_history.json` is the history
store. The extra cost is one tiny read per render (needed for the forecast
anyway) plus a write **only when `used_pct` changed** (pct is a step function),
not every render.

### Functions

- `record_sample(window, pct, now, history) -> history`
  Append `(now, pct)` **only if `pct` differs from the last recorded sample**
  for that window (`used_pct` is a step function — it only changes when a
  request is made — so this keeps the series meaningful and writes rare).
  Prune to the lookback window + max count.
- `burn_rate(samples, now, lookback_s) -> Optional[float]`
  Over samples within `lookback_s` of `now`, compute `Δpct / Δt` (first→last).
  Return `None` if < 2 samples, `Δt` too small, or rate ≤ 0 (not burning).
  Units: percent per second.
- `time_to_limit(used_pct, rate) -> Optional[float]`
  `(100 - used_pct) / rate` seconds, or `None` if `rate` is None/≤0 or already
  ≥ 100%.
- `forecast_chip(window, used_pct, resets_at, now, history, lookback_s) -> Optional[str]`
  Orchestrates: record the sample, compute `burn_rate`, `time_to_limit`, and the
  time-to-reset from `resets_at`. If `time_to_limit < time_to_reset`, return the
  compact `~<duration>` string; else `None`. Returns `None` (never raises) on any
  missing/invalid input.
- A small `format_eta(seconds) -> str` helper (`~40m` / `~2h10m` / `~30s`),
  or reuse an existing compact formatter.

### Lookback constants (provisional — tune empirically)

- `five_hour`: recent ~30 min (wider than a first guess of 15 min: `used_pct` is
  a step function, and the 5h window is the one users care most about — too
  short risks `<2 samples → None` and the chip never firing for 5h).
- `seven_day`: recent ~2 h.

These set **sensitivity only** (not correctness — see safe degradation) and are
expected to be tuned after observing real data; flagged provisional in code.

### Render integration

`core.main`, when `cfg.show_forecast` and official rate-limits are present:
lazy-`import` `predict` (deferred inside the forecast branch, like `.activity`/
`.identity`, so `test_import_perf` doesn't see it eagerly), read
`rate_history.json` once, compute `forecast_chip` for 5h and 7d. The whole block
is wrapped in `try/except` → on any failure, no chips (never blanks the bar),
mirroring the activity-scan guard.

**Chip is passed RAW, colored by the renderer** (mirrors the `cache_age_text`
precedent in `render_classic`, styles.py): `forecast_chip` returns just the raw
`~40m` string (or `None`); `core.main` passes `forecast_5h`/`forecast_7d` raw
strings down; `render_classic`/`format_status_line` apply the severity color
(`s_hot` when the duration is ≤ ~10 min, else `s_warn`) and `_strip` correctly
under `use_color=False`.

**Plumbing — two new params + a NEW 7d append site.** `format_status_line`
currently appends `countdown_emoji` only to the **5h** segment; the **7d**
segment has no trailing slot. So:
- add params `forecast_5h=""`, `forecast_7d=""` to `format_status_line`;
- 5h: append the chip right after the existing `⏰{reset}{countdown_emoji}`;
- 7d: add a **new** append point after `⏰{reset_time_7d}` for `forecast_7d`;
- `render_classic` accepts both and forwards them; `styles.render` passes them
  through; `core.main` supplies them.

### Config wiring (`show_forecast`, default True)

Five touch-points in `config.py`/`cli.py` (same ceremony as the other flags):
1. `StatusbarConfig.show_forecast: bool = True` (dataclass default);
2. `load_config`: `show_forecast=_to_bool(raw.get("show_forecast", True))`;
3. add `"show_forecast"` to `VALID_KEYS`;
4. add `"show_forecast"` to `_BOOL_KEYS`;
5. add a `print(... show_forecast ...)` line in `cs config show` (cli.py).

## Data flow (per render, when enabled)

1. read `rate_history.json` (tiny; empty/`{}` if missing or corrupt).
2. `forecast_chip` records the current sample (write only if `pct` changed) and
   computes the chip for each window.
3. chips passed to the renderer, appended after the reset timers.

## Concurrency

Multiple windows render concurrently and append to the same global file. Atomic
write (tmp + rename) prevents corruption. Read-modify-write under N concurrent
writers is last-writer-wins, so a window can drop another's just-appended sample
— meaning under heavy multi-window use the history can **undercount** samples
(weakening, not breaking, the estimate). This is acceptable for a forecast.

**Mitigation:** in the common **daemon (fast) mode** the long-lived daemon
renders every session each tick and is effectively the single writer, so the
race barely arises. Inline (non-daemon) mode also records (so the forecast still
works there), accepting the benign undercount. Because the quota is
account-global, one shared file is correct (not per-session).

## Edge cases / error handling

- < 2 samples / `Δt` ≤ 0 (clock skew) / rate ≤ 0 → no chip.
- `resets_at` missing → can't compare → no chip.
- `used_pct` ≥ 100 → already capped → no chip (the bar already shows it).
- history file missing/corrupt/unreadable JSON → treat as empty, rebuild.
- entire forecast computation wrapped in `try/except` in `core.main` →
  degrades to "no chip", never blanks the bar (runs before main's big try).
- non-numeric / out-of-range `used_pct` → coerced/ignored (reuse existing `_pct`
  hygiene where possible).

## Hot-path cost

When `show_forecast` is on: one small JSON read per render, plus an occasional
atomic write (only when `used_pct` changed). The file is tiny (bounded sample
count), so this is cheap relative to the existing transcript tail-scans. No
banned imports added (test_import_perf invariant preserved).

## Testing

- `burn_rate`: ≥2 samples → correct %/s; <2 → None; Δt≤0 → None; rate≤0 → None;
  respects lookback (old samples excluded).
- `time_to_limit`: normal; rate None/0 → None; used_pct ≥ 100 → None.
- `forecast_chip`: at-risk (ttl < time-to-reset) → `~<dur>` string; safe → None;
  missing resets_at → None; insufficient samples → None; clock skew → None.
- `record_sample`: appends only on pct change (dedup); prunes to lookback + max
  count; atomic write; corrupt/missing file → empty history.
- `format_eta`: `~40m` / `~2h10m` / `~30s`.
- Render: `format_status_line` / `render_classic` with a risk chip → chip appears
  right after the matching `⏰reset`; `show_forecast` off → no chip; `use_color=False`
  output is ANSI-clean; chip colour = hot when ttl small, warn otherwise.
- Config: `show_forecast` default True; round-trips via `cs config set`; listed
  in `cs config show`.
- Robustness: corrupt history file → no crash, no chip.

## Out of scope (future sub-projects)

- Desktop notifications (approaching-limit / window-reset ping).
- Projected end-of-window % display mode.
- Capsule/hairline chip rendering (unless trivial to fold in).
