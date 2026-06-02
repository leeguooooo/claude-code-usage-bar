# Rate-limit projection model — design

**Date:** 2026-06-02
**Status:** approved for one-shot implementation planning
**Scope:** replace the always-visible projection numbers for the 5h and 7d
rate-limit windows. This is separate from the at-risk `⚠~ETA` chip.

## Goal

The status line should always show an estimated end-of-window percentage:

```text
5h →50% | 7d →90%
```

The number means: "if usage continues according to the best model currently
available, this window is expected to reset at about this percentage."

The feature must work from cold start, collect local history immediately, and
improve as it observes more real usage. It should still be measurable: every
projection model must log enough data to compare predictions against actual
window outcomes.

## Non-goals

- Do not hide the projection because confidence is low. The product decision is
  to always show a number.
- Do not show confidence labels such as `low`, `med`, or `learning` in the main
  status line.
- Do not rely on Claude internals beyond the official status-line payload:
  `used_percentage`, `resets_at`, model/context metadata, and timestamps.
- Do not make the `⚠~ETA` warning chip the projection model. Warnings can reuse
  projection data later, but the projection segment has its own purpose.
- Do not make prediction accuracy impossible to audit. Hidden weights are
  acceptable only if the persisted snapshots make the resulting error measurable.

## Single Delivery Scope

Implement the complete projection system in one pass:

- timestamped account-global samples;
- projection snapshots and reset-outcome error logging;
- 5h blended projection from recent rate, whole-window average, and personal
  coarse-bucket baseline;
- 7d future-bucket integration using learned coarse buckets with default priors;
- wall-clock/sample-based output smoothing;
- `show_projection` config;
- explicit coexistence with `⚠~ETA`.

The implementation should still be internally separable so each piece can be
tested independently, but the product ships as one feature rather than staged
rollouts.

## Accuracy Measurement

Projection accuracy is a first-class feature requirement.

For every window, store projection snapshots:

```json
{
  "window": "seven_day",
  "observed_at": 1780390000.0,
  "used_pct": 10.0,
  "resets_at": 1780927200.0,
  "model": "projection_v1",
  "projected_pct": 62.0
}
```

When `resets_at` changes, close the previous window and record:

```json
{
  "window": "seven_day",
  "previous_resets_at": 1780927200.0,
  "actual_final_pct": 68.0,
  "closed_at": 1780927205.0
}
```

Then compute error for snapshots that targeted that reset:

```text
absolute_error = abs(projected_pct - actual_final_pct)
```

Track at least:

- mean absolute error by window and model;
- median absolute error by window and model;
- error by lead time bucket, for example projections made 1h, 6h, 24h, and 3d
  before reset;
- how often `projection_v1` is worse than simple baselines such as whole-window
  average for 5h and fixed-prior bucket integration for 7d.

This is not a rollout gate. It is an ongoing audit trail so future tuning can be
based on measured error instead of eyeballing the status line.

## Data Model

Store one account-global projection file, separate from `last_stdin.json`:

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
  },
  "snapshots": [],
  "closed_windows": []
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
- Store projection snapshots and closed-window outcomes in the same bounded file
  or a sibling bounded metrics file. The exact file split is an implementation
  detail; the measurement data must exist.

## Shared Signal Extraction

For each window, derive these signals from current input and bounded history:

- `current_used_pct`: the newest valid sample for the current window.
- `current_window_avg_rate`: current usage divided by inferred elapsed window
  time. This is a fallback, not the primary 7d model.
- `recent_rate_60m`, `recent_rate_24h`: slope over recent samples when there is
  enough span. Avoid very short 15m slopes because `used_pct` is an integer step
  function.
- `default_bucket_prior`: conservative default rhythm used at cold start.
- `personal_baseline`: learned local rate by coarse time bucket.
- `sample_coverage`: how much observed evidence exists for this window/model.

Invalid or noisy slopes should be ignored, not allowed to dominate:

- too little elapsed time;
- only one sample;
- zero or negative time delta;
- short-interval spikes caused by delayed official refresh;
- impossible jumps after clamping.

## Window Semantics Check

The projection formula depends on whether the official window is fixed or
rolling.

- Fixed-window behavior: usage accumulates until `resets_at`, then resets. The
  formula `current_used_pct + expected_future_usage_until_reset` is valid.
- Rolling-window behavior: old usage can age out before `resets_at`. In that
  case, adding future usage to current usage double-counts usage that will expire.

The feature must record enough samples to observe the semantics:

- Does `used_pct` ever fall while `resets_at` is unchanged?
- Does `resets_at` move continuously or jump at boundaries?
- Near reset, does usage drop sharply or gradually?

If rolling behavior is observed, the 7d model must estimate expected age-out or
reduce the weight of `current_used_pct + future_usage` style projections. The
error log is the backstop: rolling-window mistakes must be visible in measured
reset error.

## 5h Model

The 5h projection should reflect current working rhythm while resisting integer
step noise and delayed official refreshes.

Formula shape:

```text
projected_5h =
  current_used_pct
  + blended_5h_rate * time_to_reset
```

`blended_5h_rate` is a weighted blend:

```text
recent_60m_rate
current_window_avg_rate
personal_5h_baseline
```

The weights adapt to evidence:

- cold start: mostly `current_window_avg_rate` plus default bucket prior;
- enough 60m sample span: increase recent-rate weight;
- enough local history in the current coarse bucket: increase personal-baseline
  weight;
- noisy or tiny-sample slope: ignore recent rate for that calculation.

Cold-start behavior:

- With almost no history, use `current_window_avg_rate` plus default bucket prior
  so a number appears immediately.
- As 60m history becomes available, increase recent-rate weight.
- As multi-day history becomes available, let the personal baseline stabilize
  estimates during idle or low-sample periods.

Expected behavior:

- Busy recent work raises the projection.
- Idle recent periods lower it.
- A single short spike must not permanently dominate.
- The output can move faster than 7d because the 5h window is intentionally
  sensitive to the current session.

## 7d Model

The 7d projection should model future rhythm, not the average of the first few
hours of the current seven-day window.

Formula shape:

```text
projected_7d =
  current_used_pct
  + sum(expected_bucket_rate(bucket) * bucket_duration_until_reset)
```

Use a small bucket table:

```text
night
weekday_work_hours
weekday_non_work_hours
weekend
```

This gets the important shape right: work time, rest time, and weekend time are
not equivalent. It also avoids the sparse-data problem of learning
weekday/weekend x 24 hourly buckets from a single user's first few days.

Each bucket rate is a blend of default prior and personal history:

```text
expected_bucket_rate =
  default_bucket_prior * prior_weight
  + learned_bucket_rate * learned_weight
```

`learned_weight` increases with sample coverage in that bucket. Finer
hour-of-day buckets are out of scope for this implementation because 48 sparse
single-user buckets would be hard to learn and hard to explain.

Cold-start behavior:

- Always show a number.
- Start from default coarse bucket priors.
- Use current-window average only as a low-weight sanity input, never as the main
  driver for 7d.
- As personal history grows, learned coarse buckets gradually replace priors.

Expected behavior:

- Early-week heavy usage should not automatically extrapolate to a full week of
  equal intensity.
- Work-hour usage should contribute more than sleep-hour usage even at cold
  start, through the fixed baseline.
- Weekend buckets should be separate from weekdays.
- 7d output should be smoother than 5h.

## Default Priors

Before enough personal history exists, use simple default priors:

- low or zero overnight usage;
- moderate weekday work-hour usage;
- lower evening and weekend usage;
- no assumption that the current first 12-24 hours represent the whole week.

The exact constants should be conservative and easy to tune. Their purpose is to
produce a reasonable initial number until personal data gradually replaces them.

Bucket rates are percent-per-hour values. This assumes the effective quota size
is stable. If the user's plan changes or Anthropic changes limit sizing, old
bucket rates may become stale; keep a model/version marker and allow the history
to be reset or down-weighted when obvious limit behavior changes.

## Output Smoothing

The status line shows a plain number, so the number itself must not thrash.

Maintain a stored `display.projected_pct` per window and smooth new estimates by
sample time, not by render count:

```text
dt = observed_at - previous_display.updated_at
alpha = 1 - exp(-dt / tau_seconds)
display = previous_display * (1 - alpha) + raw_projection * alpha
```

Only update smoothing when a new valid sample is recorded or when enough wall
clock time has passed to recompute future-bucket integration. Do not apply the
EWMA once per 1Hz render tick; otherwise daemon mode, inline mode, and multiple
Claude windows would produce different projections for the same real data.

Recommended behavior:

- 5h uses a shorter time constant because it should react to current work.
- 7d uses a longer time constant because weekly projections should be stable.
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

Configuration:

- `show_projection: bool = True` controls the `→NN%` projection numbers.
- Existing `show_forecast` continues to control the `⚠~ETA` warning chips.

Coexistence with warning chips:

```text
5h[...17%...]⏰2h43m →50% ⚠~1h20m
7d[...9%...]⏰6d05h →90%
```

- The projection appears first because it explains expected end-of-window usage.
- The warning chip appears after it only when the separate ETA logic determines
  the window is on track to hit 100% before reset.
- If projection is `→100%` or higher and ETA also exists, show both. They answer
  different questions: final expected percentage vs time to cap.

## Error Handling

- Missing/corrupt history file: rebuild from the current sample and default
  priors.
- Missing `resets_at`: show current usage as the projection for that window.
- Missing `used_pct`: reuse the previous display value briefly; if no previous
  display value exists, show `0%` rather than removing the projection segment.
- Clock skew or future/past impossible samples: ignore the bad sample.
- Any exception in projection code must never blank the status line.

## Testing

Unit tests:

- records timestamped samples and accepts newer lower same-reset values;
- prunes history without losing current-window evidence;
- computes 5h projection from recent slopes, whole-window average, and personal
  baseline;
- falls back to current-window average at cold start;
- computes 7d projection by integrating future time buckets;
- distinguishes work-hour, non-work-hour, weekend, and overnight buckets;
- blends default priors with learned bucket rates by sample coverage;
- smooths by wall-clock/sample time rather than render count;
- smooths 7d with a longer time constant than 5h;
- never displays below current usage;
- keeps `show_projection` separate from `show_forecast`;
- renders projection before ETA when both are present;
- survives corrupt history and malformed input.

Scenario tests:

- first 18 hours of a 7d window are busy, then future includes sleep/weekend
  periods: projection should not equal `current_window_avg * 7d`;
- 5h starts idle then becomes busy: projection should rise within the next few
  samples;
- 5h starts busy then idles: projection should fall without waiting for reset;
- same `resets_at` with lower newer reading: history should accept it and avoid
  stale high-value pollution;
- daemon 1Hz render and inline render with the same sample timestamps produce the
  same smoothed projection;
- plan/limit behavior changes can down-weight or reset stale bucket history.

## Migration

The current `rate_latest.json` can be ignored or read once as a seed. The new
history file should be the source of truth for projections.

Existing `show_forecast` controls warning chips only. Add `show_projection`
defaulting to true for the `→NN%` projection numbers.
