# Per-segment color management + classic theme adoption — design

## Problem

Two coupled issues, both surfacing as "the bar isn't refined":

**(1) Color bleed (classic).** When `7d` hits warning severity, the *entire*
line tints yellow: the `5h` label, the `|` separators, the model name, the
reset times. This is because `format_status_line` derives a single
`overall_color = max severity over all dimensions` and applies it to every
non-bar element. Separate metrics blur into one color band.

**(2) Classic ignores themes (the "色调不够雅" issue).** `progress.py` uses
**raw 8-color ANSI** — `\033[32m / 33m / 31m` foregrounds and `\033[42m / 43m
/ 41m` backgrounds — which terminals render in their own (typically saturated)
default palette. The whole `themes.py` system (`graphite`, `twilight`,
`linen`, `nord`, `dracula`, `sakura`, `mono`) only affects `capsule` and
`hairline`. Switching theme has zero visual effect on classic. So users see
the terminal's loud default green/yellow/red instead of the theme's tuned
RGB tones.

The `capsule` and `hairline` styles already separate segments via distinct pill
hues (capsule) and per-segment mini-bars (hairline), but neither currently
surfaces **context** (`ctx_used_pct`) severity, so a near-full context window
is invisible until something else trips the warning.

## Goal

1. Each metric segment owns its own color and severity story. No segment's
   color leaks into another's.
2. All three styles surface `5h`, `7d`, `context`, and `cache` independently.
   The numeric segments (5h, 7d, context) share the same 30/70 thresholds so
   "yellow = warning" stays consistent across them; cache keeps its existing
   string-age severity logic (see Out of scope).
3. Classic respects the active theme — same red/green/yellow *concepts*, but
   pulled from `theme.s_ok / s_warn / s_hot` RGB, and same neutral text from
   `theme.ink / theme.mute`.
4. Visual identity unchanged: battery bar with overlaid percentage, `[ ]`
   brackets, `🕐` / `⏰` clock emojis, and ` | ` separators all stay. This is
   a palette + scoping refinement, not a redesign.

## Out of scope

- New thresholds. Context reuses the existing `warning_threshold` /
  `critical_threshold` (defaults 30/70).
- Layout / glyph / bar shape changes. No replacement of `[ ]`, `🕐⏰`,
  ` | `, the battery bar, or the `(used/size)` parens. The visual identity
  stays.
- New styles. No `fluent` or other addition; the three existing styles are the
  product surface.
- Severity-threshold model for cache. Cache is string-age based
  (`styles.py::_cache_severity` maps `"COLD"` / `"<1m"` / longer to its own
  three-level scale) and stays that way. The shared 30/70 thresholds apply
  only to numeric percentages: 5h, 7d, context.

In scope, **mandatory** as part of this change:
- A new `theme.pill_cost` field added to every theme (see Risks → "Capsule
  cost pill hue"). This *is* a theme palette change; included intentionally
  as the cleanest fix for the cost/lang collision.

In scope but optional, eyeball-decided after the classic hookup lands:
- A small graphite `s_warn` desaturation tweak (`(232,178,96)` →
  `(214,168,92)`) if the larger battery-bar background reads as harsh.

## Design

### Coloring rules (all three styles)

| Segment      | Severity source                | Notes |
|--------------|--------------------------------|-------|
| 5h           | `msgs_pct`                     | already plumbed |
| 7d           | `weekly_pct`                   | already plumbed |
| context      | `ctx_used_pct` (newly plumbed) | hidden when no `context_window_size` |
| cache        | cache age (existing logic)     | unchanged |
| `$` cost     | none (neutral ink)             | de-coupled from any segment |
| lang `📚`    | unchanged (green)              | |
| `⚠ BYPASS`   | unchanged (always red)         | |

Severity → color mapping (existing): `s_ok` (calm), `s_warn` (≥ warning),
`s_hot` (≥ critical). All *numeric percentage* segments (5h, 7d, context)
use the same 30/70 thresholds so the *meaning* of yellow and red is
consistent across the bar. Cache keeps its existing string-age severity
logic (see Out of scope).

### Style-by-style changes

**`classic`** — biggest change. Three coordinated edits:

*(a) Drop `overall_color` (per-segment scoping)*
- `5h` label, bar, reset countdown → colored by `msgs_pct` severity only.
- `7d` label, bar, reset countdown → colored by `weekly_pct` severity only.
- Model + context block (`Opus 4.7(280.0k/1.0M)`) → colored by `ctx_used_pct`
  severity. Falls back to neutral `theme.ink` when context isn't available.
- `$` cost → neutral `theme.ink`.
- ` | ` separator → `theme.mute` (dim) so it never carries any segment's color.
- `cache` segment → unchanged logic, but uses theme RGB (see (b)).

*(b) Classic respects the theme (the "雅"-ness fix)*

Replace every raw ANSI code in `progress.py` with theme-driven RGB. The
mapping is one-for-one — the *concept* (green = calm, yellow = warning,
red = critical) is preserved; only the actual color values change to
match the active theme.

| Today (progress.py)                  | After                                      |
|--------------------------------------|--------------------------------------------|
| `GREEN = "\033[32m"`                 | `_fg(theme.s_ok)`                          |
| `YELLOW = "\033[33m"`                | `_fg(theme.s_warn)`                        |
| `RED = "\033[31m"`                   | `_fg(theme.s_hot)`                         |
| `BG_GREEN = "\033[42m"` (battery)    | `_bg(theme.s_ok)`                          |
| `BG_YELLOW = "\033[43m"` (battery)   | `_bg(theme.s_warn)`                        |
| `BG_RED = "\033[41m"` (battery)      | `_bg(theme.s_hot)`                         |
| `BG_GRAY = "\033[100m"` (empty cell) | `_bg(theme.edge)`                          |
| `FG_WHITE = "\033[97m"` (overlay)    | `_fg(theme.pill_ink)` (high contrast)      |
| `DIM = "\033[2m"`                    | `_fg(theme.mute)`                          |

The `_fg` / `_bg` helpers already exist in `styles.py` — `progress.py`
should import or duplicate them (lean toward import; `progress.py` is
already a sibling module). `format_status_line` accepts a `theme: Theme`
parameter so the renderer can pass the active theme through.

*(c) Hierarchy via mute (visual layer separation)*
- `[` and `]` brackets around the battery bar → `theme.mute`. Today they
  inherit `overall_color`, so the brackets pop as bright as the data —
  they should recede behind the percentage.
- `(` and `)` around `(280.0k/1.0M)` → `theme.mute`. The numbers inside
  stay severity-colored.
- ` | ` separator → `theme.mute` (already covered above, listed here for
  completeness).
- `⏰` / `🕐` clock emojis stay as-is (emoji color is not under our
  control on most terminals; forcing fg ANSI on them produces inconsistent
  behavior across iTerm / Terminal.app / Alacritty).

**`capsule`** — already segregated by pill hues. Two small additions:
- Model pill gains a severity dot driven by `ctx_used_pct`, mirroring how 5h/7d
  pills already show their `●` dots. No dot when context is unavailable.
- `$` cost pill moves off `theme.pill_lang` onto the new `theme.pill_cost`
  field (see Risks). Currently the cost pill and language pill share the
  same hue, which is itself a "colors mixing" problem in the capsule style.

**`hairline`** — already per-segment; one small addition:
- Model text gets its severity color from `ctx_used_pct` (mirrors how `5h`
  percentage uses ink + the mini3 below uses severity). Falls back to `INK`
  when context isn't available.

### Plumbing

`ctx_used_pct` already arrives in stdin (`core.py:1148`, `core.py:1181`) but is
discarded after computing the `(used/size)` display string.

**`ctx_pct` nullability contract.** The renderer must distinguish "context
not surfaced" from "context at 0%". The discriminator is
`context_window_size`, not `context_used_pct`:

- `context_window_size <= 0` (or absent) → context segment not surfaced;
  `ctx_pct = None`.
- `context_window_size > 0` → context surfaced; `ctx_pct = float(raw_pct)`,
  where `raw_pct = stdin_data.get('context_used_pct', 0)`. A genuine 0%
  context (early in session) renders as calm `s_ok`, identical to 5h/7d
  at 0%.

Rule: `core.py` computes `ctx_pct: Optional[float]` as follows:
```
ctx_size = stdin_data.get('context_window_size', 0)
raw_pct  = stdin_data.get('context_used_pct', 0)
ctx_pct  = float(raw_pct) if ctx_size > 0 else None
```
**Note on the falsy-0 trap:** an earlier draft used
`if (ctx_size > 0 and raw_pct)`, but `raw_pct = 0` is falsy in Python and
would route genuine 0% to `None` — making 0% context indistinguishable from
"no context data". The size gate alone is the correct discriminator.

Renderers receive `Optional[float]` and treat `None` as "use neutral
`theme.ink` for the model text; no severity dot in capsule".

New wiring:

1. `core.py` — compute `ctx_pct` per the rule above; pass it into
   `_render_style`. The `(used/size)` display string keeps using the raw
   `0` defaults for its own purposes (it's already gated on `ctx_size > 0`).
2. `styles.py::render_classic` / `render_capsule` / `render_hairline` — accept
   a new `ctx_pct: Optional[float]` kwarg. Threaded explicitly (not via
   `**_ignored`) so the contract is visible.
3. `progress.py::format_status_line` — accept a `theme: Theme` parameter (or
   pull from a `get_theme(name)` import); drop `overall_color`; color each
   dimension by its own pct via `color_for_percent(pct, theme=theme)`; switch
   bracket/separator/parens to `theme.mute`.
4. `progress.py::color_for_percent` / `bg_for_percent` — accept `theme` and
   return `_fg(theme.s_*)` / `_bg(theme.s_*)` instead of raw ANSI strings.
   Existing call sites updated.
5. `progress.py::build_battery_bar` — receive `theme`; use `theme.pill_ink`
   for the overlaid percentage text and `theme.edge` for empty cells.
6. `progress.py::_build_dimension` — already accepts a color arg; each call
   now passes its own per-pct color (which is now an RGB ANSI string from
   the theme).
7. `progress.py::format_language_segment` — currently hardcodes `GREEN`
   (`progress.py:250`). Pull from `theme.s_ok` instead. **Note:** language
   coloring is not unified across styles. Classic uses green, capsule uses
   `theme.pill_lang` (`styles.py:113`), hairline uses `MUTE`
   (`styles.py:181`). This change touches classic only; capsule and
   hairline keep their existing language treatment. The lang line in the
   "Coloring rules" table refers to classic.
8. `preview.py` — currently classifies classic as `THEME_AGNOSTIC`
   (`preview.py:117-119`) and emits one row instead of looping over themes
   (`preview.py:141-155`). After this change classic *does* depend on the
   theme, so:
   - Remove `"classic"` from the `THEME_AGNOSTIC` set.
   - Let classic flow through the per-theme loop alongside capsule and
     hairline. `cs preview --style classic --theme graphite|nord|...` then
     produces visibly different palettes per row, which is the regression
     test for the theme hookup.

The legacy module-level constants are imported by two source surfaces, both
inside the rewrite scope:

- `styles.py::render_classic` — `GREEN` at `styles.py:207`, plus
  `GREEN, YELLOW, RED` at `styles.py:223`. Both call sites get rewritten to
  use `theme.s_ok / s_warn / s_hot` directly.
- `tests/test_progress.py` — multi-site:
  - `RED` imported at module level (`tests/test_progress.py:33`) and used by
    `test_colorize` (`tests/test_progress.py:71`) and
    `test_colorize_no_color` (`tests/test_progress.py:76`).
  - `GREEN / YELLOW / RED` used in `color_for_percent` threshold assertions
    around `tests/test_progress.py:44-60`.
  All migrate to theme-driven equivalents (e.g.
  `_fg(get_theme("graphite").s_hot)`).

**Decision:** drop the module-level `GREEN` / `YELLOW` / `RED` / `BG_*` /
`FG_WHITE` / `DIM` constants. Keep `RESET` (it's protocol, not palette).
The migration is contained: two source surfaces, both updated in this
change. Grep confirmed no other module reads them.

### Edge cases

- **No stdin / no `context_window_size`** → `ctx_pct = None` → model text
  rendered in neutral `INK` (classic, hairline) or no severity dot (capsule).
  Behavior identical to today's "no context block" rendering, just without the
  inherited overall_color tint.
- **`use_color = False`** → existing `_strip` paths in `styles.py` continue to
  scrub ANSI; classic uses `colorize(..., use_color=False)` which is already a
  no-op. No new code paths needed.
- **`ctx_used_pct = 0`** (early in session) → treated as calm (`s_ok`), same as
  5h/7d at 0%.
- **`ctx_used_pct > 100`** (shouldn't happen but possible from model overruns)
  → `color_for_percent` already clamps via the `>=` checks; falls into critical.

## Testing

Unit tests in `tests/test_progress.py` (existing) and a new
`tests/test_per_segment_colors.py`. Theme-aware assertions: build the
expected ANSI by calling `_fg(theme.s_ok)` on the test's theme rather than
hardcoding RGB.

**Per-segment scoping (classic):**
- `5h=10 / 7d=80 / ctx=20`: `5h` label uses `s_ok` fg, `7d` label uses
  `s_warn` fg, model uses `s_ok` fg, separator uses `mute` fg, brackets use
  `mute` fg. No `s_warn` ANSI appears anywhere on the `5h` segment.
- `ctx=85`: model/context block carries `s_hot` fg even when `5h=10` and
  `7d=10` are calm.
- No `context_window_size`: model text has no severity codes (neutral
  `theme.ink`).
- `use_color=False`: output is ANSI-free across all severity combinations.

**Theme adoption (classic):**
- Default theme `graphite`: `color_for_percent(20, theme=graphite)` returns
  `_fg(graphite.s_ok)` (i.e. RGB `120,200,192`), not `\033[32m`.
- Switching theme (`graphite` → `linen`) on the same input changes the
  rendered ANSI accordingly. This is the regression test that proves
  classic actually respects theme changes.
- Battery bar in `linen`: empty cells use `linen.edge` background, filled
  cells use `linen.s_ok / s_warn / s_hot` background, overlaid digits use
  `linen.pill_ink`.

**Capsule / hairline:**
- Capsule, `ctx=85`: a severity dot is present inside the model pill;
  capsule, no context: no dot.
- Capsule with `cost_text`: cost pill background is *not* `theme.pill_lang`.
- Hairline, `ctx=85`: model text uses `s_hot` fg; hairline, no context:
  model text uses `theme.ink`.

**Snapshot / visual sanity:**
- `cs preview --style classic --theme graphite|twilight|linen|nord|dracula`
  produces visibly different palettes per row (it didn't before this
  change — classic was in `THEME_AGNOSTIC`). The default `cs preview` (no
  `--theme` filter) loops 7 themes × 3 styles = 21 rows; classic now
  contributes 7 rows instead of 1.
- Existing tests in `tests/test_progress.py` (module-level `RED` import at
  line 33; `test_colorize` / `test_colorize_no_color` at lines 71/76;
  `color_for_percent` assertions at lines 44–60) migrate from raw ANSI
  constants to theme-driven equivalents like
  `_fg(get_theme("graphite").s_ok)`. Each migrated assertion explicitly
  binds to a theme so test failures point at the actual palette under
  test.

## Migration / compatibility

No config schema change. No new env vars. Themes gain one new mandatory
field — `theme.pill_cost` — added to all 7 built-in themes; existing fields
are unchanged. `cs preview` output shifts visually for classic (intentional —
that's the "雅"-ness fix). Capsule and hairline shift only in the small
additions noted above (model severity dot, cost pill recoloring).

`progress.py` removes module-level `GREEN` / `YELLOW` / `RED` / `BG_*` /
`FG_WHITE` / `DIM` constants. Both internal call sites (`styles.py`,
`tests/test_progress.py`) are updated in the same change. No external
consumer is known; `RESET` is preserved (it's a protocol token, not a
palette).

## Risks

- **Test churn** — `tests/test_progress.py` asserts equality with the raw
  ANSI constants (`color_for_percent(20) == GREEN`). Those tests become
  theme-aware: assert against `_fg(theme.s_ok)` on a chosen test theme.
  Manageable scope (one file, ~10 assertions).
- **Lower visual urgency** — when only one segment is critical, the others
  stay calm so the "everything is red" alarm effect goes away. This is
  intentional (it's the color-bleed bug being fixed) but worth flagging
  in release notes.
- **Theme palette stress test** — wiring classic into `theme.s_ok / s_warn
  / s_hot` for the first time may surface palettes that look fine in
  capsule pills but harsh in classic's larger battery-bar background fills
  (more pixels of the color = more saturation perceived). Mitigation: do a
  visual pass across all 7 themes once classic-接主题 lands; if any theme
  reads as too saturated, dial down the offending `s_*` RGB. The optional
  graphite `s_warn` (232,178,96) → (214,168,92) tweak in "Out of scope" is
  the first candidate.
- **Capsule cost pill hue** — moving cost off `pill_lang` requires picking
  a destination. **Decision: add a dedicated `theme.pill_cost` field** to
  every theme, one new RGB per theme (7 themes × one tuple). The field is
  *mandatory* and added in this change; only the exact RGB values are an
  implementation-time detail. Reusing `pill_model` would put cost and model
  in adjacent same-color pills, which is the very collision this change is
  trying to fix. Initial RGB derivation: take each theme's existing
  `pill_lang` RGB and desaturate ~15% so the cost pill reads as a quieter
  sibling rather than a competing hue. The 7 final numbers get picked
  during implementation; they're a tuning detail, not a design decision.
