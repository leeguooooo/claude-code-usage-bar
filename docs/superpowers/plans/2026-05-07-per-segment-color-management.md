# Per-segment color management + classic theme adoption — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Each metric segment (5h / 7d / context / cache) colors itself by its own severity; classic style finally respects the theme system; brackets/parens/separators recede via `theme.mute`. Visual identity unchanged.

**Architecture:** `progress.py` (the classic-style renderer) gains a `theme: Theme` parameter and switches every raw-ANSI constant to `_fg(theme.s_*)` / `_bg(theme.s_*)`. `format_status_line` drops the `overall_color = max(severity)` rule in favor of per-segment severity. `core.py` plumbs a nullable `ctx_pct` through to the renderer so classic, capsule, and hairline can all color the model/context block by context-window severity. `themes.py` gains one mandatory `pill_cost` field per theme to break the cost/lang collision in capsule. `preview.py` removes classic's `THEME_AGNOSTIC` exemption.

**Tech Stack:** Python 3.11, pytest, no new deps.

**Spec:** `docs/superpowers/specs/2026-05-07-per-segment-color-management-design.md` (commit `8278d14`)

**File structure:**

| File | Responsibility | Touch type |
|---|---|---|
| `src/claude_statusbar/themes.py` | Theme dataclass + 7 built-in palettes | Modify — add `pill_cost` field |
| `src/claude_statusbar/progress.py` | Pure rendering for classic-style status line | Modify — major rewrite (theme-driven, per-segment) |
| `src/claude_statusbar/styles.py` | Three style renderers | Modify — render_classic/capsule/hairline updates |
| `src/claude_statusbar/core.py` | Stdin → render dispatch | Modify — compute nullable `ctx_pct`, thread through |
| `src/claude_statusbar/preview.py` | `cs preview` command output | Modify — drop classic from `THEME_AGNOSTIC` |
| `tests/test_progress.py` | Existing progress tests | Modify — migrate off raw ANSI constants |
| `tests/test_per_segment_colors.py` | New: per-segment scoping + theme adoption | Create |

---

## Task 1: Add `theme.pill_cost` field to all 7 themes

The cost pill recolor (capsule, Task 3) consumes this field. Initial RGB
values below are **illustrative starters**, not pinned by the spec — pick
final numbers during implementation by desaturating each theme's
`pill_lang` ~15% and eyeballing in `cs preview`.

**Files:**
- Modify: `src/claude_statusbar/themes.py:14-101`
- Test: `tests/test_styles.py` (add assertion at end)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_styles.py`:

```python
def test_every_theme_has_pill_cost():
    """pill_cost is mandatory and distinct from pill_lang for every theme."""
    for t in BUILTIN_THEMES:
        assert hasattr(t, "pill_cost"), f"{t.name} missing pill_cost"
        assert isinstance(t.pill_cost, tuple) and len(t.pill_cost) == 3, \
            f"{t.name}.pill_cost must be an RGB 3-tuple"
        assert t.pill_cost != t.pill_lang, \
            f"{t.name}.pill_cost must differ from pill_lang (collision is the bug)"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_styles.py::test_every_theme_has_pill_cost -v`
Expected: FAIL — `AttributeError: 'Theme' object has no attribute 'pill_cost'`

- [ ] **Step 3: Add `pill_cost` field to the `Theme` dataclass**

In `src/claude_statusbar/themes.py`, after the existing `pill_lang: RGB` line:

```python
    pill_lang: RGB
    pill_cost: RGB   # cost pill bg — separate from pill_lang to avoid collision
    pill_ink: RGB    # text color used on pill backgrounds
```

- [ ] **Step 4: Populate `pill_cost` for every built-in theme**

For each of the 7 themes in `BUILTIN_THEMES`, add a `pill_cost=(...)` field. **Illustrative starter values** (final numbers chosen during implementation by desaturating each theme's `pill_lang` ~15% and eyeballing):

| Theme | Current pill_lang | Starter pill_cost |
|---|---|---|
| graphite | (52, 65, 47) | (48, 56, 50) |
| twilight | (50, 72, 90) | (52, 68, 80) |
| linen | (202, 210, 194) | (198, 200, 192) |
| nord | (46, 52, 64) | (52, 58, 64) |
| dracula | (50, 80, 60) | (52, 70, 62) |
| sakura | (220, 230, 215) | (218, 222, 212) |
| mono | (50, 50, 50) | (60, 60, 60) |

The only hard constraints (asserted by Step 1's test): values must be RGB 3-tuples and must differ from `pill_lang`.

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_styles.py::test_every_theme_has_pill_cost -v`
Expected: PASS

- [ ] **Step 6: Run the full theme/style test suite to confirm no regressions**

Run: `uv run pytest tests/test_styles.py -v`
Expected: ALL PASS (capsule still uses `pill_lang` for cost — that's fixed in Task 3).

- [ ] **Step 7: Commit**

```bash
git add src/claude_statusbar/themes.py tests/test_styles.py
git commit -m "feat(themes): add pill_cost field to all 7 themes

Mandatory new field used by the capsule cost pill so it stops
sharing pill_lang with the language pill. Initial RGB values
derived by ~15% desaturation from each theme's pill_lang."
```

---

## Task 2: Rewrite `progress.py` + update `styles.py::render_classic` (atomic)

This is the biggest task. It does four things atomically because they're inseparable: extends function signatures with `theme`, switches internals from raw ANSI to theme RGB, drops `overall_color` in favor of per-segment severity, and updates `styles.py::render_classic` so it stops importing the constants this commit removes. Tests in `test_progress.py` migrate in the same commit since they pin the legacy ANSI constants that disappear here.

**Why atomic:** removing `GREEN/YELLOW/RED` from `progress.py` while leaving them imported in `styles.py:207` and `:223` would break `tests/test_styles.py` at the commit boundary. The only way to keep the suite green between commits is to land both edits together. Codex review pass 1 flagged this as a blocker.

**Files:**
- Modify: `src/claude_statusbar/progress.py` (major)
- Modify: `src/claude_statusbar/styles.py:199-237` (render_classic — drop legacy imports, thread theme + ctx_pct)
- Modify: `tests/test_progress.py:33-77` (drop legacy constants, migrate to theme-driven)
- Create: `tests/test_per_segment_colors.py`

**Sub-step plan:** write new tests → see them fail → rewrite progress.py → rewrite render_classic → migrate old tests → all pass → commit.

- [ ] **Step 1: Write the new per-segment test file**

Create `tests/test_per_segment_colors.py`:

```python
"""Per-segment color management tests for the classic style.

Every numeric segment (5h, 7d, context) colors itself by its own pct.
No segment's color leaks into another. The | separator and [ ] / ( )
brackets are always theme.mute so they don't carry severity.
"""
import re
from claude_statusbar.progress import format_status_line, _fg
from claude_statusbar.themes import get_theme

GRAPHITE = get_theme("graphite")
ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def _ansi_for(rgb):
    return f"\033[38;2;{rgb[0]};{rgb[1]};{rgb[2]}m"


def test_per_segment_severity_isolation():
    """5h calm, 7d warning: separator + brackets stay mute,
    no warning ANSI appears around the 5h segment."""
    line = format_status_line(
        msgs_pct=10, tkns_pct=None, reset_time="2h00m",
        weekly_pct=80, reset_time_7d="3d00h",
        model="Opus 4.7", ctx_pct=None,
        theme=GRAPHITE, use_color=True,
    )
    s_ok = _ansi_for(GRAPHITE.s_ok)
    s_warn = _ansi_for(GRAPHITE.s_warn)
    mute = _ansi_for(GRAPHITE.mute)
    # 5h segment must contain s_ok, must not contain s_warn
    five_h_chunk = line.split("|")[0]
    assert s_ok in five_h_chunk
    assert s_warn not in five_h_chunk
    # 7d segment must contain s_warn
    seven_d_chunk = line.split("|")[1]
    assert s_warn in seven_d_chunk
    # Separator and brackets carry mute
    assert mute in line


def test_ctx_pct_critical_colors_model():
    """ctx_pct=85 paints the model block s_hot even when 5h/7d are calm."""
    line = format_status_line(
        msgs_pct=10, tkns_pct=None, reset_time="2h00m",
        weekly_pct=10, reset_time_7d="3d00h",
        model="Opus 4.7(900k/1M)", ctx_pct=85,
        theme=GRAPHITE, use_color=True,
    )
    s_hot = _ansi_for(GRAPHITE.s_hot)
    # Find the model chunk (between the second and third | separators)
    model_chunk = line.split("|")[2]
    assert s_hot in model_chunk


def test_ctx_pct_none_uses_theme_ink():
    """ctx_pct=None means model text is neutral (theme.ink), no severity."""
    line = format_status_line(
        msgs_pct=10, tkns_pct=None, reset_time="2h00m",
        weekly_pct=10, reset_time_7d="3d00h",
        model="Opus 4.7", ctx_pct=None,
        theme=GRAPHITE, use_color=True,
    )
    ink = _ansi_for(GRAPHITE.ink)
    s_hot = _ansi_for(GRAPHITE.s_hot)
    s_warn = _ansi_for(GRAPHITE.s_warn)
    model_chunk = line.split("|")[2]
    # Model in neutral ink, no severity
    assert ink in model_chunk
    assert s_hot not in model_chunk
    assert s_warn not in model_chunk


def test_ctx_pct_zero_renders_calm():
    """Genuine 0% context (early in session) is calm s_ok, not None."""
    line = format_status_line(
        msgs_pct=10, tkns_pct=None, reset_time="2h00m",
        weekly_pct=10, reset_time_7d="3d00h",
        model="Opus 4.7(0/1M)", ctx_pct=0.0,
        theme=GRAPHITE, use_color=True,
    )
    s_ok = _ansi_for(GRAPHITE.s_ok)
    assert s_ok in line.split("|")[2]


def test_theme_switch_changes_classic_palette():
    """Same input rendered under graphite vs linen produces different ANSI.
    This is the regression test that proves classic actually respects themes."""
    args = dict(
        msgs_pct=10, tkns_pct=None, reset_time="2h00m",
        weekly_pct=10, reset_time_7d="3d00h",
        model="Opus 4.7", ctx_pct=None, use_color=True,
    )
    line_g = format_status_line(theme=get_theme("graphite"), **args)
    line_l = format_status_line(theme=get_theme("linen"), **args)
    assert line_g != line_l
    # graphite.s_ok and linen.s_ok are visibly distinct
    assert _ansi_for(get_theme("graphite").s_ok) in line_g
    assert _ansi_for(get_theme("linen").s_ok) in line_l


def test_use_color_false_strips_ansi():
    """All severity combinations produce ANSI-free output when use_color=False."""
    line = format_status_line(
        msgs_pct=80, tkns_pct=None, reset_time="2h00m",
        weekly_pct=80, reset_time_7d="3d00h",
        model="Opus 4.7(900k/1M)", ctx_pct=85,
        theme=GRAPHITE, use_color=False,
    )
    assert ANSI_RE.search(line) is None


def test_brackets_use_theme_mute():
    """[ and ] around the battery bar are colored theme.mute, not severity."""
    line = format_status_line(
        msgs_pct=80, tkns_pct=None, reset_time="2h00m",
        weekly_pct=10, reset_time_7d="3d00h",
        model="Opus 4.7", ctx_pct=None,
        theme=GRAPHITE, use_color=True,
    )
    mute = _ansi_for(GRAPHITE.mute)
    # brackets appear with mute prefix (the bare '[' character is preceded by mute ANSI)
    assert f"{mute}[" in line
    assert f"{mute}]" in line


def test_parens_around_context_use_theme_mute():
    """( and ) wrapping (used/size) are theme.mute; the numbers inside stay severity."""
    line = format_status_line(
        msgs_pct=10, tkns_pct=None, reset_time="2h00m",
        weekly_pct=10, reset_time_7d="3d00h",
        model="Opus 4.7(280k/1M)", ctx_pct=20,
        theme=GRAPHITE, use_color=True,
    )
    mute = _ansi_for(GRAPHITE.mute)
    assert f"{mute}(" in line
    assert f"{mute})" in line


def test_paren_muting_targets_the_last_bracket_not_the_first():
    """Model names that already contain parens (e.g. version annotations)
    must not have THOSE muted — only the trailing (used/size) bracket.
    Regression test for a regex anchor bug."""
    line = format_status_line(
        msgs_pct=10, tkns_pct=None, reset_time="2h00m",
        weekly_pct=10, reset_time_7d="3d00h",
        model="Opus(beta) 4.7(280k/1M)", ctx_pct=20,
        theme=GRAPHITE, use_color=True,
    )
    mute = _ansi_for(GRAPHITE.mute)
    s_ok = _ansi_for(GRAPHITE.s_ok)
    # The "(beta)" group should be in severity color, NOT mute.
    # The "(280k/1M)" group should have mute parens.
    # Detect by checking that "(beta" appears with severity color prefix,
    # while "(280k" appears with mute prefix.
    assert f"{s_ok}Opus(beta)" in line or f"{mute}(beta)" not in line
    assert f"{mute}(" in line  # the LAST paren is muted
```

- [ ] **Step 2: Run new tests to verify they fail**

Run: `uv run pytest tests/test_per_segment_colors.py -v`
Expected: ALL FAIL — most with `ImportError: cannot import name '_fg'` from progress, or `TypeError: format_status_line() got an unexpected keyword argument 'theme'`. That's the failing-test baseline.

- [ ] **Step 3: Rewrite `progress.py`**

Replace the whole file with the new theme-driven implementation. Key changes:

1. Import `_fg` / `_bg` helpers from `styles.py`, OR define them locally (recommended: define locally to avoid circular imports — `styles.py` already imports from `progress.py`).
2. Drop module-level `GREEN / YELLOW / RED / BG_GREEN / BG_YELLOW / BG_RED / BG_GRAY / FG_WHITE / DIM` constants. Keep `RESET`, `FILL`, `EMPTY`, `DEFAULT_WARNING_THRESHOLD`, `DEFAULT_CRITICAL_THRESHOLD`.
3. `color_for_percent(pct, theme=None, warning_threshold=None, critical_threshold=None)` — fall back to `get_theme("graphite")` when theme is None; return `_fg(theme.s_*)`.
4. `bg_for_percent(pct, theme=None, ...)` — same pattern, returns `_bg(theme.s_*)`.
5. `build_battery_bar(percent, width=10, use_color=True, theme=None, warning_threshold=None, critical_threshold=None)` — empty cells use `_bg(theme.edge)`, filled cells use `_bg(theme.s_*)`, overlay text uses `_fg(theme.pill_ink)`.
6. `_build_dimension(label, pct, severity_color, use_color, warning_threshold, critical_threshold, theme)` — now also colors the brackets with `_fg(theme.mute)`.
7. `format_status_line(msgs_pct, tkns_pct, reset_time, model, weekly_pct=None, reset_time_7d="", ctx_pct=None, bypass=False, use_color=True, countdown_emoji="", warning_threshold=None, critical_threshold=None, lang_text="", cost_text="", theme=None)` — drops `overall_color`; computes `color_5h` / `color_7d` per-segment; `model_color = _fg(theme.ink) if ctx_pct is None else color_for_percent(ctx_pct, theme=theme, ...)`; separator → `_fg(theme.mute)`.
8. `format_status_line` muting of model parens: split `model` on the **last** `(...)` group (handles model names that contain version annotations like `Opus(beta) 4.7(280k/1M)` — the version paren stays in severity color, only the trailing context paren is muted); render `name + mute( + inner + mute) + tail`. If no parens, render whole model in `model_color`.

Reference implementation sketch (full file replacement — adapt exactly):

```python
"""Progress bar rendering for the status bar. Pure functions, no I/O."""

import json
import re
from pathlib import Path
from typing import Optional

from .themes import Theme, get_theme

FILL = "█"
EMPTY = "░"
RESET = "\033[0m"

DEFAULT_WARNING_THRESHOLD = 30.0
DEFAULT_CRITICAL_THRESHOLD = 70.0


def _fg(rgb): return f"\033[38;2;{rgb[0]};{rgb[1]};{rgb[2]}m"
def _bg(rgb): return f"\033[48;2;{rgb[0]};{rgb[1]};{rgb[2]}m"


def normalize_thresholds(warning_threshold=None, critical_threshold=None):
    warning = DEFAULT_WARNING_THRESHOLD if warning_threshold is None else float(warning_threshold)
    critical = DEFAULT_CRITICAL_THRESHOLD if critical_threshold is None else float(critical_threshold)
    if not 0 <= warning < critical <= 100:
        raise ValueError("Thresholds must satisfy 0 <= warning < critical <= 100.")
    return warning, critical


def build_bar(percent, width=10):
    clamped = max(0.0, min(percent, 100.0))
    filled = int(clamped / 100 * width + 0.5)
    if percent > 0 and filled == 0:
        filled = 1
    return FILL * filled + EMPTY * (width - filled)


def color_for_percent(percent, theme=None, warning_threshold=None, critical_threshold=None):
    theme = theme or get_theme("graphite")
    warning, critical = normalize_thresholds(warning_threshold, critical_threshold)
    if percent >= critical:
        return _fg(theme.s_hot)
    if percent >= warning:
        return _fg(theme.s_warn)
    return _fg(theme.s_ok)


def bg_for_percent(percent, theme=None, warning_threshold=None, critical_threshold=None):
    theme = theme or get_theme("graphite")
    warning, critical = normalize_thresholds(warning_threshold, critical_threshold)
    if percent >= critical:
        return _bg(theme.s_hot)
    if percent >= warning:
        return _bg(theme.s_warn)
    return _bg(theme.s_ok)


def colorize(text, color, use_color=True):
    if not use_color:
        return text
    return f"{color}{text}{RESET}"


def build_battery_bar(percent, width=10, use_color=True, theme=None,
                      warning_threshold=None, critical_threshold=None):
    theme = theme or get_theme("graphite")
    clamped = max(0.0, min(percent, 100.0))
    filled = int(clamped / 100 * width + 0.5)
    if percent > 0 and filled == 0:
        filled = 1
    text = "MAX" if percent > 100 else f"{percent:.0f}%"
    padded = text.center(width)
    if not use_color:
        result = ""
        for i, ch in enumerate(padded):
            if ch == " ":
                result += FILL if i < filled else EMPTY
            else:
                result += ch
        return result
    bg_fill = bg_for_percent(percent, theme=theme,
                             warning_threshold=warning_threshold,
                             critical_threshold=critical_threshold)
    bg_empty = _bg(theme.edge)
    fg_overlay = _fg(theme.pill_ink)
    result = ""
    for i, ch in enumerate(padded):
        if i < filled:
            result += f"{bg_fill}{fg_overlay}{ch}"
        else:
            result += f"{bg_empty}{fg_overlay}{ch}"
    result += RESET
    return result


def _build_dimension(label, pct, severity_color, use_color,
                     warning_threshold, critical_threshold, theme):
    mute = _fg(theme.mute)
    if pct is not None:
        bar = build_battery_bar(pct, use_color=use_color, theme=theme,
                                warning_threshold=warning_threshold,
                                critical_threshold=critical_threshold)
    else:
        if use_color:
            bar = f"{_bg(theme.edge)}{_fg(theme.pill_ink)}" + "--%".center(10) + RESET
        else:
            bar = EMPTY * 3 + "--%" + EMPTY * 4
    return (
        colorize(label, severity_color, use_color)
        + colorize("[", mute, use_color)
        + bar
        + colorize("]", mute, use_color)
    )


# ── language-segment helpers (unchanged signatures, switched to theme.s_ok) ──

_LANGUAGE_OVERRIDES = {"Chinese": "ZH", "Japanese": "JA"}
def _language_code(language): return _LANGUAGE_OVERRIDES.get(language, language[:2].upper())
def _language_trend(estimates):
    if not isinstance(estimates, list) or len(estimates) < 2:
        return "→"
    try:
        previous = float(estimates[-2].get("band"))
        current = float(estimates[-1].get("band"))
    except (AttributeError, TypeError, ValueError):
        return "→"
    if current > previous: return "↑"
    if current < previous: return "↓"
    return "→"
def _coach_enabled(config_path="~/.claude/language-coach.json"):
    try:
        cfg = json.loads(Path(config_path).expanduser().read_text(encoding="utf-8"))
        return bool(cfg.get("enabled", False))
    except (OSError, json.JSONDecodeError, ValueError):
        return False
MAX_LANGUAGES = 4
def format_language_body(progress_path):
    if not _coach_enabled():
        return ""
    path = Path(progress_path).expanduser()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    parts = []
    for language in sorted(payload):
        entry = payload.get(language)
        if not isinstance(entry, dict):
            continue
        current_band = entry.get("currentBand")
        if not isinstance(current_band, str) or not current_band:
            continue
        trend = _language_trend(entry.get("estimates"))
        parts.append(f"{_language_code(str(language))}:{current_band}{trend}")
        if len(parts) >= MAX_LANGUAGES:
            break
    return " ".join(parts)
def format_language_segment(progress_path, use_color=True, theme=None):
    body = format_language_body(progress_path)
    if not body:
        return ""
    theme = theme or get_theme("graphite")
    return colorize(f"📚 {body}", _fg(theme.s_ok), use_color)


def get_countdown_emoji(minutes_to_reset):
    if minutes_to_reset is None:
        return ""
    if minutes_to_reset <= 1: return " \U0001f389"
    if minutes_to_reset <= 10: return " ✨"
    if minutes_to_reset <= 30: return " ⚡"
    return ""


def _format_model(model, severity_color, mute_color, use_color):
    """Render `Opus 4.7(280.0k/1.0M)` with the parens muted and the rest
    in severity_color. Falls back to a single-color render when no parens.

    Anchors to the LAST `(...)` group so model names that already contain
    parens (e.g. `Opus(beta) 4.7(280k/1M)`) get their context bracket
    muted, not the version annotation. The greedy `.*` swallows everything
    up to the last paren group; the non-greedy `.*?` tail then matches
    whatever (usually nothing) follows it.
    """
    m = re.match(r"^(.*)(\([^)]*\))(.*?)$", model)
    if not m:
        return colorize(model, severity_color, use_color)
    name, parens, tail = m.groups()
    inner = parens[1:-1]
    return (
        colorize(name, severity_color, use_color)
        + colorize("(", mute_color, use_color)
        + colorize(inner, severity_color, use_color)
        + colorize(")", mute_color, use_color)
        + colorize(tail, severity_color, use_color)
    )


def format_status_line(
    msgs_pct, tkns_pct, reset_time, model,
    weekly_pct=None, reset_time_7d="",
    ctx_pct=None,
    bypass=False, use_color=True,
    countdown_emoji="",
    warning_threshold=None, critical_threshold=None,
    lang_text="", cost_text="",
    theme=None,
):
    """Build the complete classic-style status line.

    Each numeric segment colors itself: 5h by msgs_pct, 7d by weekly_pct,
    model by ctx_pct (None => neutral theme.ink). Separator and brackets
    use theme.mute. (used/size) parens muted, numbers stay severity.
    """
    theme = theme or get_theme("graphite")
    warning_threshold, critical_threshold = normalize_thresholds(
        warning_threshold, critical_threshold
    )
    mute = _fg(theme.mute)
    ink = _fg(theme.ink)

    color_5h = color_for_percent(
        msgs_pct if msgs_pct is not None else 0,
        theme=theme,
        warning_threshold=warning_threshold,
        critical_threshold=critical_threshold,
    ) if msgs_pct is not None else mute
    color_7d = color_for_percent(
        weekly_pct if weekly_pct is not None else 0,
        theme=theme,
        warning_threshold=warning_threshold,
        critical_threshold=critical_threshold,
    ) if weekly_pct is not None else mute

    dim_5h = _build_dimension("5h", msgs_pct, color_5h, use_color,
                              warning_threshold, critical_threshold, theme)
    dim_5h += colorize(f"⏰{reset_time}{countdown_emoji}", color_5h, use_color)
    parts = [dim_5h]

    dim_7d = _build_dimension("7d", weekly_pct, color_7d, use_color,
                              warning_threshold, critical_threshold, theme)
    if reset_time_7d:
        dim_7d += colorize(f"⏰{reset_time_7d}", color_7d, use_color)
    parts.append(dim_7d)

    if ctx_pct is None:
        model_color = ink
    else:
        model_color = color_for_percent(
            ctx_pct, theme=theme,
            warning_threshold=warning_threshold,
            critical_threshold=critical_threshold,
        )
    parts.append(_format_model(model, model_color, mute, use_color))

    if cost_text:
        parts.append(colorize(f"$ {cost_text}", ink, use_color))
    if lang_text:
        parts.append(lang_text)
    if bypass:
        parts.append(colorize("⚠️BYPASS", _fg(theme.s_hot), use_color))

    separator = colorize(" | ", mute, use_color)
    return separator.join(parts)
```

- [ ] **Step 4: Migrate `tests/test_progress.py` off legacy ANSI constants**

In `tests/test_progress.py`:

1. Remove the imports of `GREEN, YELLOW, RED` at line 33-39. Replace with:

```python
from claude_statusbar.progress import (
    color_for_percent,
    colorize,
    normalize_thresholds,
    _fg,
    RESET,
)
from claude_statusbar.themes import get_theme

_TH = get_theme("graphite")
GREEN_FG = _fg(_TH.s_ok)
YELLOW_FG = _fg(_TH.s_warn)
RED_FG = _fg(_TH.s_hot)
```

2. Update the assertions at lines 44-60 to compare against `GREEN_FG`/`YELLOW_FG`/`RED_FG` and pass `theme=_TH` to `color_for_percent`:

```python
def test_color_safe():
    assert color_for_percent(20, theme=_TH) == GREEN_FG

def test_color_warning():
    assert color_for_percent(50, theme=_TH) == YELLOW_FG

def test_color_critical():
    assert color_for_percent(80, theme=_TH) == RED_FG

def test_color_boundary_30():
    assert color_for_percent(30, theme=_TH) == YELLOW_FG

def test_color_boundary_70():
    assert color_for_percent(70, theme=_TH) == RED_FG

def test_color_custom_thresholds():
    assert color_for_percent(39, theme=_TH, warning_threshold=40, critical_threshold=80) == GREEN_FG
    assert color_for_percent(40, theme=_TH, warning_threshold=40, critical_threshold=80) == YELLOW_FG
    assert color_for_percent(80, theme=_TH, warning_threshold=40, critical_threshold=80) == RED_FG
```

3. Update `test_colorize` (line 71) and `test_colorize_no_color` (line 76) to use `RED_FG`:

```python
def test_colorize():
    result = colorize("hello", RED_FG)
    assert result == f"{RED_FG}hello{RESET}"

def test_colorize_no_color():
    result = colorize("hello", RED_FG, use_color=False)
    assert result == "hello"
```

- [ ] **Step 5: Update `styles.py::render_classic` (same commit)**

`styles.py:207` and `styles.py:223` both import `GREEN` (and `YELLOW, RED` at line 223) from `progress.py` inside the function body. Those imports just broke. Rewrite `render_classic` so it uses `theme.s_*` directly. Replace the whole function body in `src/claude_statusbar/styles.py:199-237` with:

```python
def render_classic(
    *, msgs_pct, weekly_pct, reset_5h, reset_7d, model,
    lang_body="", cost_text="", cache_age_text="", bypass=False,
    use_color=True, theme: Optional[Theme]=None,
    warning_threshold=30.0, critical_threshold=70.0,
    countdown_emoji: str = "",
    ctx_pct: Optional[float] = None,
    **_ignored,
) -> str:
    from .progress import format_status_line, _fg, colorize, RESET
    theme = theme or get_theme("graphite")
    lang_text = (
        colorize(f"📚 {lang_body}", _fg(theme.s_ok), use_color)
        if lang_body else ""
    )
    result = format_status_line(
        msgs_pct=msgs_pct, tkns_pct=None,
        reset_time=reset_5h, model=model,
        weekly_pct=weekly_pct, reset_time_7d=reset_7d or "",
        ctx_pct=ctx_pct,
        bypass=bypass, use_color=use_color,
        countdown_emoji=countdown_emoji,
        warning_threshold=warning_threshold,
        critical_threshold=critical_threshold,
        lang_text=lang_text,
        cost_text=cost_text,
        theme=theme,
    )
    if cache_age_text:
        # Three-level severity: COLD red, <1m yellow, otherwise green.
        if cache_age_text == "COLD":
            col = _fg(theme.s_hot)
        elif "m" in cache_age_text or "h" in cache_age_text:
            col = _fg(theme.s_ok)
        else:
            col = _fg(theme.s_warn)
        mute = _fg(theme.mute)
        result += f"{RESET}{colorize(' | ', mute, use_color)}{colorize(f'cache {cache_age_text}', col, use_color)}"
    return result
```

Notes:
- Cache separator switches to `theme.mute` so it matches the rest of the bar's separator style.
- The unused `format_language_segment` import is dropped.

- [ ] **Step 6: Run the entire affected test suite**

Run: `uv run pytest tests/test_progress.py tests/test_per_segment_colors.py tests/test_styles.py tests/test_cache_severity.py -v`
Expected: ALL PASS. The atomicity is what keeps this green — `progress.py` and `styles.py::render_classic` move together.

- [ ] **Step 7: Run import-perf regression test**

Run: `uv run pytest tests/test_import_perf.py -v`
Expected: PASS — `progress.py` now imports `themes.py`, but the fast path is in `render_thin.py` which already defers progress.py imports per `tests/test_import_perf.py:85-91`.

- [ ] **Step 8: Commit**

```bash
git add src/claude_statusbar/progress.py src/claude_statusbar/styles.py tests/test_progress.py tests/test_per_segment_colors.py
git commit -m "refactor(classic): per-segment severity + theme-driven RGB

Drop overall_color = max(severity) in format_status_line; each
numeric segment (5h, 7d, context) colors itself by its own pct.
Replace raw 8-color ANSI (\\\\033[32/33/31m fg, \\\\033[42/43/41m bg)
in progress.py with theme.s_ok/s_warn/s_hot RGB. Brackets, parens
around (used/size), and | separator move to theme.mute.

styles.py::render_classic threads theme + ctx_pct through
format_status_line; lang text and cache severity now pull from
theme.s_ok/s_warn/s_hot.

Atomic with styles.py because removing the GREEN/YELLOW/RED
module-level constants from progress.py breaks the in-function
imports at styles.py:207 and styles.py:223 — both must move
together to keep the suite green."
```

---

## Task 3: `render_capsule` — ctx_pct severity dot in model pill + cost pill recolor

**Files:**
- Modify: `src/claude_statusbar/styles.py:62-127`
- Test: extend `tests/test_per_segment_colors.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_per_segment_colors.py`:

```python
from claude_statusbar.styles import render_capsule

def test_capsule_model_pill_has_severity_dot_when_ctx_critical():
    out = render_capsule(
        msgs_pct=10, weekly_pct=10, reset_5h="2h", reset_7d="3d",
        model="Opus 4.7(900k/1M)", ctx_pct=85,
        use_color=True, theme=GRAPHITE,
    )
    s_hot = _ansi_for(GRAPHITE.s_hot)
    # Severity dot is `●` colored s_hot, present inside the model pill area.
    assert "●" in out
    assert s_hot in out


def test_capsule_model_pill_no_dot_when_ctx_none():
    out = render_capsule(
        msgs_pct=10, weekly_pct=10, reset_5h="2h", reset_7d="3d",
        model="Opus 4.7", ctx_pct=None,
        use_color=True, theme=GRAPHITE,
    )
    # Without context info, no severity dot inside the model pill.
    # 5h/7d still have their own dots, so we look for absence in the
    # plain-text sequence between "Opus" and the next pill boundary.
    plain = re.sub(r"\033\[[0-9;]*m", "", out)
    model_idx = plain.find("Opus")
    # Walk forward from model_idx to the next ╱ separator
    next_sep = plain.find("╱", model_idx) if "╱" in plain[model_idx:] else len(plain)
    model_segment = plain[model_idx:next_sep]
    assert "●" not in model_segment


def test_capsule_cost_pill_uses_pill_cost_not_pill_lang():
    """The cost pill must use theme.pill_cost, not theme.pill_lang."""
    out = render_capsule(
        msgs_pct=10, weekly_pct=10, reset_5h="2h", reset_7d="3d",
        model="Opus 4.7", ctx_pct=None, cost_text="3.14",
        use_color=True, theme=GRAPHITE,
    )
    pill_cost_bg = f"\033[48;2;{GRAPHITE.pill_cost[0]};{GRAPHITE.pill_cost[1]};{GRAPHITE.pill_cost[2]}m"
    pill_lang_bg = f"\033[48;2;{GRAPHITE.pill_lang[0]};{GRAPHITE.pill_lang[1]};{GRAPHITE.pill_lang[2]}m"
    assert pill_cost_bg in out
    # When there's no lang_body, pill_lang must NOT appear at all
    assert pill_lang_bg not in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_per_segment_colors.py::test_capsule_model_pill_has_severity_dot_when_ctx_critical tests/test_per_segment_colors.py::test_capsule_model_pill_no_dot_when_ctx_none tests/test_per_segment_colors.py::test_capsule_cost_pill_uses_pill_cost_not_pill_lang -v`
Expected: FAIL — capsule doesn't accept `ctx_pct`, doesn't render dot, cost pill still on `pill_lang`.

- [ ] **Step 3: Edit `render_capsule`**

In `src/claude_statusbar/styles.py:62`:

1. Add `ctx_pct: Optional[float] = None` to the signature.
2. After the `parts.append(pill(theme.pill_model, ...))` line for the model pill (around line 107), modify to inline a severity dot when `ctx_pct is not None`:

```python
    # Model pill — gains a ctx_pct severity dot (mirrors 5h/7d dots).
    model_body = f"{BOLD}◆{RESET}{INK}{_bg(theme.pill_model)} {model}{sev_dot(ctx_pct)}{INK}{_bg(theme.pill_model)}"
    parts.append(pill(theme.pill_model, model_body))
```

(`sev_dot` already exists locally and returns empty string when its arg is None.)

3. Change the cost pill from `theme.pill_lang` to `theme.pill_cost`:

```python
    if cost_text:
        parts.append(pill(theme.pill_cost, f"$ {cost_text}"))
```

- [ ] **Step 4: Run capsule tests**

Run: `uv run pytest tests/test_per_segment_colors.py -k capsule -v`
Expected: PASS for all 3 new capsule tests.

- [ ] **Step 5: Run full styles test to confirm no regression**

Run: `uv run pytest tests/test_styles.py -v`
Expected: ALL PASS.

- [ ] **Step 6: Commit**

```bash
git add src/claude_statusbar/styles.py tests/test_per_segment_colors.py
git commit -m "feat(capsule): ctx_pct severity dot + cost pill on pill_cost

Model pill gains a severity dot driven by ctx_used_pct (mirrors
5h/7d dots; absent when ctx_pct is None). Cost pill moves off
theme.pill_lang onto theme.pill_cost to fix the color collision
with the language pill."
```

---

## Task 4: `render_hairline` — ctx_pct severity for model text

**Files:**
- Modify: `src/claude_statusbar/styles.py:132-193`
- Test: extend `tests/test_per_segment_colors.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_per_segment_colors.py`:

```python
from claude_statusbar.styles import render_hairline

def test_hairline_model_uses_ctx_severity_when_critical():
    out = render_hairline(
        msgs_pct=10, weekly_pct=10, reset_5h="2h", reset_7d="3d",
        model="Opus 4.7", ctx_pct=85,
        use_color=True, theme=GRAPHITE,
    )
    s_hot = _ansi_for(GRAPHITE.s_hot)
    # Find the chunk containing "Opus" — it must be wrapped in s_hot
    plain = re.sub(r"\033\[[0-9;]*m", "", out)
    assert "Opus" in plain
    # The colored model text must use s_hot
    assert f"{s_hot}Opus" in out or s_hot in out.split("Opus")[0][-30:]


def test_hairline_model_uses_ink_when_no_ctx():
    out = render_hairline(
        msgs_pct=10, weekly_pct=10, reset_5h="2h", reset_7d="3d",
        model="Opus 4.7", ctx_pct=None,
        use_color=True, theme=GRAPHITE,
    )
    ink = _ansi_for(GRAPHITE.ink)
    # Model text uses neutral theme.ink
    assert ink in out
    # No severity ANSI bleeds into the model area
    assert _ansi_for(GRAPHITE.s_hot) not in out.split("Opus")[0][-30:]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_per_segment_colors.py -k hairline -v`
Expected: FAIL — hairline doesn't accept `ctx_pct`, uses INK unconditionally.

- [ ] **Step 3: Edit `render_hairline`**

In `src/claude_statusbar/styles.py:132`:

1. Add `ctx_pct: Optional[float] = None` to the signature.
2. Replace the model line `parts.append(f"{MUTE}›{RESET} {INK}{model}{RESET}")` with conditional severity:

```python
    # Model line — colored by ctx_pct severity, neutral ink when absent
    if ctx_pct is None:
        model_color = INK
    else:
        col = _severity_color(theme, ctx_pct, warning_threshold, critical_threshold)
        model_color = _fg(col)
    parts.append(f"{MUTE}›{RESET} {model_color}{model}{RESET}")
```

- [ ] **Step 4: Run hairline tests**

Run: `uv run pytest tests/test_per_segment_colors.py -k hairline -v`
Expected: PASS.

- [ ] **Step 5: Run full styles test**

Run: `uv run pytest tests/test_styles.py tests/test_per_segment_colors.py -v`
Expected: ALL PASS.

- [ ] **Step 6: Commit**

```bash
git add src/claude_statusbar/styles.py tests/test_per_segment_colors.py
git commit -m "feat(hairline): model text uses ctx_pct severity

Mirrors classic and capsule. Model text colors itself by
ctx_used_pct severity; falls back to theme.ink when ctx_pct
is None (no context_window_size in stdin)."
```

---

## Task 5: `core.py` — compute nullable `ctx_pct` and thread through

**Files:**
- Modify: `src/claude_statusbar/core.py:1146-1208` (two render-call sites)
- Test: `tests/test_core_ctx_pct.py` (new, integration-flavored)

- [ ] **Step 1: Write the failing test**

The cleanest way to test the ctx_pct discriminator is to exercise the small block of `core.py` that computes it, not to spin up the full subprocess. The discriminator is logic-only and side-effect-free.

**API shape note:** Claude Code's stdin nests context info under a `context_window` key with `used_percentage` (not `context_used_pct`). `core.py:568-575` reads from that nested structure and *flattens* it onto the top level as `context_used_pct` and `context_window_size` for downstream code. So the discriminator at `core.py:1146-1158` reads from the *already-flattened* shape. Tests should therefore feed the flattened shape (the `stdin_data` dict that the discriminator sees), not the raw API payload.

Create `tests/test_core_ctx_pct.py`:

```python
"""Unit tests for the ctx_pct nullable-discriminator logic in core.py.

The discriminator runs against a flattened stdin_data dict produced by
core.py:568-575 (which reads `data['context_window']['used_percentage']`
and writes it as top-level `context_used_pct`). These tests feed the
already-flattened shape directly.
"""


def _compute_ctx_pct(stdin_data):
    """Mirror the discriminator that lives at core.py:1146-1158 (after
    Step 3 below lands). Kept here as a self-contained helper so the
    test pins the exact contract independent of surrounding core.py code."""
    ctx_size = stdin_data.get("context_window_size", 0)
    raw_pct = stdin_data.get("context_used_pct", 0)
    return float(raw_pct) if ctx_size > 0 else None


def test_no_context_window_yields_none():
    """Missing context_window_size means context segment is not surfaced."""
    assert _compute_ctx_pct({}) is None
    assert _compute_ctx_pct({"context_used_pct": 50}) is None  # size=0
    assert _compute_ctx_pct({"context_window_size": 0, "context_used_pct": 50}) is None


def test_zero_pct_context_renders_calm():
    """Genuine 0% (early in session) returns 0.0, not None.
    This is the falsy-0 trap from spec review."""
    out = _compute_ctx_pct({"context_window_size": 1_000_000, "context_used_pct": 0})
    assert out == 0.0
    assert out is not None


def test_normal_context_returns_float():
    out = _compute_ctx_pct({"context_window_size": 1_000_000, "context_used_pct": 42})
    assert out == 42.0
    assert isinstance(out, float)
```

- [ ] **Step 2: Run to verify the tests fail (or pass trivially because the helper is self-contained)**

Run: `uv run pytest tests/test_core_ctx_pct.py -v`
Expected: ALL PASS. (The helper mirrors the contract; the test pins it. If a future refactor of `core.py` changes the discriminator, the test still pins what `core.py` MUST do — kept in sync via Step 3 review.)

This is more of a contract pin than a failing-then-passing TDD cycle. The actual integration confidence comes from the existing test suite continuing to pass after Step 3-4.

- [ ] **Step 3: Edit `core.py` — replace ctx_pct discriminator at line ~1147**

In `src/claude_statusbar/core.py`, find the block around line 1146-1158:

```python
            # Append context window usage to model name: Opus 4.6(10k/1M)
            ctx_size = stdin_data.get('context_window_size', 0)
            ctx_pct = stdin_data.get('context_used_pct', 0)
            if ctx_pct and ctx_size:
                ctx_used = int(ctx_size * ctx_pct / 100)
            else:
                ctx_used = stdin_data.get('total_input_tokens', 0) + stdin_data.get('total_output_tokens', 0)
            if ctx_size > 0:
                # Strip redundant size suffix like "(1M context)" from display_name
                import re as _re
                model = _re.sub(r'\s*\([^)]*context[^)]*\)', '', model)
                model = f"{model}({format_number(ctx_used)}/{format_number(ctx_size)})"
```

Rename the local `ctx_pct` variable so it doesn't shadow the value being passed downstream, and compute the nullable sentinel:

```python
            # Append context window usage to model name: Opus 4.6(10k/1M)
            ctx_size = stdin_data.get('context_window_size', 0)
            raw_pct = stdin_data.get('context_used_pct', 0)
            # ctx_pct: Optional[float] for the renderer.
            # ctx_size > 0 is the discriminator (not raw_pct, which is falsy at 0%).
            ctx_pct = float(raw_pct) if ctx_size > 0 else None
            if raw_pct and ctx_size:
                ctx_used = int(ctx_size * raw_pct / 100)
            else:
                ctx_used = stdin_data.get('total_input_tokens', 0) + stdin_data.get('total_output_tokens', 0)
            if ctx_size > 0:
                import re as _re
                model = _re.sub(r'\s*\([^)]*context[^)]*\)', '', model)
                model = f"{model}({format_number(ctx_used)}/{format_number(ctx_size)})"
```

Add `ctx_pct=ctx_pct` to the `_render_style(...)` call right after this block (around line 1161):

```python
                print(_render_style(
                    chosen_style,
                    msgs_pct=msgs_pct, weekly_pct=weekly_pct,
                    reset_5h=reset_time, reset_7d=reset_time_7d,
                    model=model, lang_body=lang_body, cost_text=cost_text,
                    bypass=bypass, cache_age_text=cache_age_text,
                    use_color=use_color, theme=chosen_theme,
                    warning_threshold=warning_threshold,
                    critical_threshold=critical_threshold,
                    countdown_emoji=countdown,
                    density=cfg.density, show_weekly=cfg.show_weekly,
                    ctx_pct=ctx_pct,
                ))
```

- [ ] **Step 4: Repeat the same pattern at the other render site (line ~1180)**

The `else: # _has_stdin but no rate_limits` branch at lines 1178-1208 has the same shape. Apply the identical rename + `ctx_pct=ctx_pct` plumbing there.

- [ ] **Step 5: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS.

- [ ] **Step 6: Run import-perf regression test**

Run: `uv run pytest tests/test_import_perf.py -v`
Expected: PASS — `core.py` was already heavy; the new sentinel doesn't add imports.

- [ ] **Step 7: Commit**

```bash
git add src/claude_statusbar/core.py tests/test_core_ctx_pct.py
git commit -m "feat(core): compute nullable ctx_pct for renderer

ctx_size > 0 is the discriminator for whether the context segment
is surfaced. Genuine 0% context renders calm; missing context_window
renders neutral. Plumbed through both _render_style call sites in
the rate-limits and stdin-only branches."
```

---

## Task 6: `preview.py` — drop `"classic"` from `THEME_AGNOSTIC`

**Files:**
- Modify: `src/claude_statusbar/preview.py:117-119`
- Test: extend `tests/test_preview.py` (or add a new assertion)

- [ ] **Step 1: Inspect the current preview test**

Run: `cat /Users/leo/github.com/claude-statusbar-monitor/tests/test_preview.py | head -80`
Note the existing test patterns so the new assertion fits in.

- [ ] **Step 2: Write the failing assertion**

`preview.py` doesn't expose a render helper that returns a string — `run()` writes to stdout via `print()`. Use pytest's `capsys` to capture stdout while exercising both themes. Add to `tests/test_preview.py`:

```python
def test_preview_classic_varies_by_theme(capsys, monkeypatch):
    """After per-segment color management lands, classic must respect
    the active theme — different themes produce different ANSI."""
    from claude_statusbar.preview import run
    import claude_statusbar.preview as preview_mod

    # Force demo data so the test doesn't depend on a live cache file.
    monkeypatch.setattr(preview_mod, "_real_data", lambda: None)

    run(use_color=True, theme_filter="graphite", style_filter="classic")
    out_g = capsys.readouterr().out

    run(use_color=True, theme_filter="linen", style_filter="classic")
    out_l = capsys.readouterr().out

    # Both renders produce non-empty output containing the model.
    assert "Opus" in out_g and "Opus" in out_l
    # The two themes must produce different ANSI (the regression).
    assert out_g != out_l
```

- [ ] **Step 3: Run to verify it fails**

Run: `uv run pytest tests/test_preview.py -k vary -v`
Expected: FAIL — classic is currently in `THEME_AGNOSTIC`, so theme is ignored.

- [ ] **Step 4: Edit `preview.py`**

In `src/claude_statusbar/preview.py:119`:

```python
# Before:
THEME_AGNOSTIC = {"classic"}

# After:
THEME_AGNOSTIC: set[str] = set()
```

(Empty set, so all three styles flow through the per-theme loop. Update the surrounding comment at lines 117-118 to reflect that classic now respects themes.)

- [ ] **Step 5: Run preview tests**

Run: `uv run pytest tests/test_preview.py -v`
Expected: ALL PASS.

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS.

- [ ] **Step 7: Commit**

```bash
git add src/claude_statusbar/preview.py tests/test_preview.py
git commit -m "feat(preview): classic renders per-theme rows

THEME_AGNOSTIC was added when classic ignored themes. With
classic now theme-aware (previous commits), it joins the
per-theme loop so cs preview shows 21 rows (7 themes × 3 styles)
instead of 15 (with classic collapsed to a single theme-agnostic row)."
```

---

## Task 7: Visual sanity pass

This task has no automated test. The implementer eyeballs `cs preview` across all 7 themes × 3 styles to catch saturation issues that automated tests can't.

**Files:** none (manual inspection)

- [ ] **Step 1: Run `cs preview` in the terminal**

Run: `uv run cs preview`
Expected: 21 rows total (7 themes × 3 styles). Classic now shows 7 distinct palettes instead of 1.

- [ ] **Step 2: Eyeball each theme**

For each of `graphite / twilight / linen / nord / dracula / sakura / mono`:
- Does the 5h battery bar background read as harsh? (large fill area amplifies saturation)
- Does the `(280k/1M)` parens color recede appropriately, or is it too dim to read?
- Does the `|` separator sit visibly behind the data?
- Do brackets `[ ]` recede behind the percentage?

- [ ] **Step 3: If any saturation issue found, dial down the offending RGB**

Most likely candidate per the spec: `graphite.s_warn = (232, 178, 96)` → consider `(214, 168, 92)`. Edit `src/claude_statusbar/themes.py` and re-run `cs preview` until the issue is resolved.

If no issues — skip directly to the final commit.

- [ ] **Step 4: Run the entire test suite one last time**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS.

- [ ] **Step 5: Final commit (only if step 3 made changes)**

```bash
git add src/claude_statusbar/themes.py
git commit -m "tune(themes): visual sanity tweaks after classic theme adoption

[Describe specific RGB changes here, e.g., graphite.s_warn
(232,178,96) → (214,168,92) to soften saturation in the larger
battery-bar background fills.]"
```

If no tuning was needed, skip this commit.

---

## Done

After Task 7, the branch is ready for PR. Summary of the change for the PR description:

> Classic style finally respects themes (the `themes.py` palette system used to only affect capsule and hairline). Each metric segment colors itself by its own severity instead of all sharing one `overall_color`. Brackets, parens, and separators recede via `theme.mute`. New mandatory `theme.pill_cost` field fixes the cost/lang collision in capsule. ctx_pct is now plumbed through to all three styles for context-window severity. Visual identity unchanged.

**Reviewed:** spec at `docs/superpowers/specs/2026-05-07-per-segment-color-management-design.md` (commit `8278d14`); 3 codex passes during brainstorming.
