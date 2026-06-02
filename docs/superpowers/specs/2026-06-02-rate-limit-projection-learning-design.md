# Rate-limit projection learning model — design

**Date:** 2026-06-02
**Status:** approved for planning
**Scope:** replace the always-visible projection numbers for the 5h and 7d
rate-limit windows. This is separate from the at-risk `⚠~ETA` chip.

## Goal

The status line should always show an estimated end-of-window percentage:

```text
5h →50% | 7d →90%
```

The number means: "if usage continues according to the best model currently
available, this window is expected to reset at about this percentage."

The feature must work from cold start and improve as it observes more local
history. Early estimates may be rough, but they should not pretend that a few
busy hours represent an entire week.

## Non-goals

- Do not hide the projection because confidence is low. The product decision is
  to always show a number.
- Do not show confidence labels such as `low`, `med`, or `learning` in the main
  status line.
- Do not rely on Claude internals beyond the official status-line payload:
  `used_percentage`, `resets_at`, model/context metadata, and timestamps.
- Do not make the `⚠~ETA` warning chip the projection model. Warnings can reuse
  projection data later, but the projection segment has its own purpose.

## Data Model

Store one account-global history file, separate from `last_stdin.json`:

```json
{
  "version": 1,
  "five_hour": [
    {
      "observed_at": 1780390000.0,
      "used_pct": 19.0,
      "resets_at": 1780399200.0,
      "session_id": "..."
    }
  ],
  "seven_day": [
    {
      "observed_at": 1780390000.0,
      "used_pct": 10.0,
      "resets_at": 1780927200.0,
      "session_id": "..."
    }
  ],
  "display": {
    "five_hour": {"projected_pct": 50.0, "updated_at": 1780390000.0},
    "seven_day": {"projected_pct": 90.0, "updated_at": 1780390000.0}
  }
}
```

Key rules:

- Record timestamped samples, not just the highest latest value.
- Accept lower percentages under the same `resets_at`; rolling-window ageing,
  official refresh correction, or stale session replacement can all produce a
  lower newer value.
- Keep samples bounded: enough history for the model, never an unbounded log.
- Write atomically. Concurrent renderers may lose a just-written sample, but must
  not corrupt the file.
- Keep this file account-global because 5h and 7d limits are account-global.

## Shared Signal Extraction

For each window, derive these signals from history:

- `current_used_pct`: the newest valid sample for the current window.
- `current_window_avg_rate`: current usage divided by inferred elapsed window
  time. This is a fallback, not the primary 7d model.
- `recent_rate_15m`, `recent_rate_60m`, `recent_rate_24h`: slope over recent
  samples when there is enough span.
- `personal_baseline`: learned local rate by time bucket.
- `sample_coverage`: how much observed evidence exists for this window/model.

Invalid or noisy slopes should be ignored, not allowed to dominate:

- too little elapsed time;
- only one sample;
- zero or negative time delta;
- short-interval spikes caused by delayed official refresh;
- impossible jumps after clamping.

## 5h Model

The 5h projection should reflect the current working rhythm. It can change
quickly, but should not jump on one delayed sample.

Formula shape:

```text
projected_5h =
  current_used_pct
  + blended_5h_rate * time_to_reset
```

`blended_5h_rate` is a weighted blend:

```text
recent_15m_rate
recent_60m_rate
current_window_avg_rate
personal_5h_baseline
```

Cold-start behavior:

- With almost no history, use `current_window_avg_rate` plus a small default
  baseline so a number appears immediately.
- As 15m/60m history becomes available, increase their weight.
- As multi-day history becomes available, let the personal baseline stabilize
  estimates during idle or low-sample periods.

Expected behavior:

- Busy recent work raises the projection.
- Idle recent periods lower it.
- A single short spike does not permanently dominate.
- The output can move faster than 7d because the 5h window is intentionally
  sensitive to the current session.

## 7d Model

The 7d projection should model personal weekly rhythm, not the average of the
first few hours of the current seven-day window.

Formula shape:

```text
projected_7d =
  current_used_pct
  + sum(expected_usage_for_each_future_time_bucket_until_reset)
```

The future usage estimate is built from time buckets:

```text
weekday/weekend + hour-of-day -> expected percent per hour
```

For example, the model should learn that weekday work hours, late nights, sleep
hours, and weekends have different rates. This lets the forecast account for
rest time and weekends instead of assuming constant 24/7 usage.

Cold-start behavior:

- Always show a number.
- Start from a conservative mix of:
  - current-window average with low weight;
  - recent 24h slope when available;
  - default daily rhythm baseline.
- As personal history grows, reduce default/current-window weight and rely more
  on learned time buckets.

Expected behavior:

- Early-week heavy usage should not automatically extrapolate to a full week of
  equal intensity.
- Work-hour usage should contribute more than sleep-hour usage when history
  supports that.
- Weekend buckets should learn separately from weekdays.
- 7d output should be smoother than 5h.

## Default Baseline

Before enough personal history exists, use a simple default rhythm:

- low or zero overnight usage;
- moderate weekday work-hour usage;
- lower evening and weekend usage;
- no assumption that the current first 12-24 hours represent the whole week.

The exact constants should be conservative and easy to tune. Their only purpose
is to produce a reasonable initial number until personal data replaces them.

## Output Smoothing

The status line shows a plain number, so the number itself must not thrash.

Maintain a stored `display.projected_pct` per window and smooth new estimates:

```text
display = previous_display * (1 - alpha) + raw_projection * alpha
```

Recommended behavior:

- 5h uses a higher alpha because it should react to current work.
- 7d uses a lower alpha because weekly projections should be stable.
- Never smooth below `current_used_pct`; the displayed projection must be at
  least current usage.
- Clamp to a sane range, normally `0..100`, unless future design explicitly
  wants to show over-limit projections.
- Allow larger jumps when `current_used_pct` itself jumps, because the displayed
  number must not lag behind observed reality.

## Display Contract

Render only the compact projection:

```text
5h →50%
7d →90%
```

Rules:

- Always show both numbers when official rate-limit data exists.
- Round to whole percentages.
- Keep the arrow form; do not add confidence labels to the main line.
- If input is malformed and no previous projection exists, fall back to current
  usage rounded to a percentage.
- The projection segment should be visually distinct from warning chips. It is
  an expected final percentage, not an urgent alert by itself.

## Error Handling

- Missing/corrupt history file: rebuild from the current sample and default
  baseline.
- Missing `resets_at`: show current usage as the projection for that window.
- Missing `used_pct`: reuse the previous display value briefly; if no previous
  display value exists, show `0%` rather than removing the projection segment.
- Clock skew or future/past impossible samples: ignore the bad sample.
- Any exception in projection code must never blank the status line.

## Testing

Unit tests:

- records timestamped samples and accepts newer lower same-reset values;
- prunes history without losing current-window evidence;
- computes 5h projection from recent slopes when available;
- falls back to current-window average at cold start;
- computes 7d projection by integrating future time buckets;
- distinguishes weekday, weekend, work-hour, and overnight buckets;
- smooths 7d more slowly than 5h;
- never displays below current usage;
- survives corrupt history and malformed input.

Scenario tests:

- first 18 hours of a 7d window are busy, then future includes sleep/weekend
  periods: projection should not equal `current_window_avg * 7d`;
- 5h starts idle then becomes busy: projection should rise within the next few
  samples;
- 5h starts busy then idles: projection should fall without waiting for reset;
- same `resets_at` with lower newer reading: history should accept it and avoid
  stale high-value pollution.

## Migration

The current `rate_latest.json` can be ignored or read once as a seed. The new
history file should be the source of truth for projections.

Existing `show_forecast` controls warning chips. The projection display should
use a separate configuration key if it needs one in the future; for this design,
the projection is treated as part of the rate-limit segment whenever official
rate-limit data exists.
