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


def _lighten(rgb, amount=0.45):
    """Blend an RGB tuple toward white by `amount` (0=unchanged, 1=white)."""
    return tuple(int(c + (255 - c) * amount) for c in rgb)


def _blend(a, b, t):
    """Blend RGB `a` toward RGB `b` by `t` (0=a, 1=b). Used to sink the
    static dot field most of the way to the bar's dark background so the
    resting field reads as faint distant stars, not a gray smear."""
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


# Particle tunables. ONE star field that twinkles in place:
#  • a STATIC field fixes WHERE the stars are — fixed cells, never moving; each
#    is a small STAR glyph (not a period), sunk near the background. SPARSE
#    (~1 cell in 4) and NEVER two in a row — a run collapses to its first cell
#    so the field never shows a mechanical `⋆⋆` pair;
#  • TWINKLE happens only at those fixed cells: a star flares bright (⋆→✦/✧)
#    1 tick in `_STAR_RARITY`, then rests. Bare sky never spawns a transient
#    star, so a bright flash always lands ON a dot — never beside it.
# Stars are the fill hue lightened; the filled color is never changed.
# The status line ticks ~1Hz, so with a sparse field this lands a flare every
# few seconds at irregular intervals — a calm twinkle, NOT a flash every second.
_STAR_RARITY = 6            # a star at a dot cell flares bright ~1 tick in N
_DOT_DENSITY = 4            # ~1 empty cell in N carries a static dot (rest = sky)
_DOT_SEED = 0x5bd1e995      # fixed seed → the dot field is phase-independent
_SPARKLE_GLINT = 0.82       # star colour = fill hue lightened this much
_DOT_SINK = 0.62            # how far the faint dot tier sinks toward background
_DOT_GLYPHS = ("⋆",)        # faint star glyph for the resting field (star-shaped, not a period)
_STAR_GLYPHS = ("✦", "✧")


def _sparkle_hash(i, phase):
    """Deterministic mixing hash of (cell index, render phase) → uint32.
    Cheap integer avalanche so adjacent cells/ticks scatter rather than march."""
    h = (i * 374761393 + phase * 668265263) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    return (h ^ (h >> 16)) & 0xFFFFFFFF


def _field_seed(label):
    """Deterministic per-bar seed from its label ("5h", "7d", …) so each bar
    gets its OWN star arrangement — without it, every width-10 bar shares the
    identical field and two side-by-side bars look like mirror-image skies."""
    return _sparkle_hash(sum(ord(c) for c in label), 0xA5A5)


def _is_dot_cell(i, seed=0):
    """Whether cell `i` is a static-dot candidate (before adjacency thinning).
    Phase-independent → the field never moves. `seed` shifts the arrangement
    per bar so the 5h and 7d skies differ."""
    return _sparkle_hash(i, _DOT_SEED + seed) % _DOT_DENSITY == 0


def _static_dot(i, seed=0):
    """Faint star glyph for the STATIC background field at cell `i`, or None
    for blank sky. Sparse (~1 cell in `_DOT_DENSITY`) and NEVER adjacent: when
    a candidate's left neighbour is also a candidate we drop this one, so a run
    collapses to its first cell and the field can't show a mechanical `⋆⋆`
    pair. Mostly dark sky with the occasional faint star behind the twinkle.
    `seed` gives each bar a distinct arrangement."""
    if not _is_dot_cell(i, seed) or (i > 0 and _is_dot_cell(i - 1, seed)):
        return None
    return _DOT_GLYPHS[_sparkle_hash(i, _DOT_SEED + seed) % len(_DOT_GLYPHS)]


def _dot_is_bright(i, seed=0):
    """Two brightness tiers for the static field → near/far star depth."""
    return bool((_sparkle_hash(i, _DOT_SEED + seed) >> 6) & 1)


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
                      warning_threshold=None, critical_threshold=None,
                      shimmer_phase=None, seed=0):
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
    warning, critical = normalize_thresholds(warning_threshold, critical_threshold)
    fill_rgb = (theme.s_hot if percent >= critical
                else theme.s_warn if percent >= warning else theme.s_ok)
    bg_fill = _bg(fill_rgb)
    bg_empty = _bg(theme.edge)
    fg_overlay = _fg(theme.pill_ink)
    # Optional particles (opt-in) in the EMPTY space: a static faint dot field
    # (never moves) overlaid with bright stars that twinkle in/out per tick.
    # The filled color is untouched — particles only occupy blank empty cells.
    star = _fg(_lighten(fill_rgb, _SPARKLE_GLINT))
    # Two depth tiers, both sunk toward the dark bar background so the resting
    # field whispers rather than smudges: `dim` is a far/faint star almost on
    # the background, `dim_bright` a nearer one at plain mute.
    dim = _fg(_blend(theme.mute, theme.edge, _DOT_SINK))
    dim_bright = _fg(theme.mute)
    result = ""
    for i, ch in enumerate(padded):
        if i < filled:
            result += f"{bg_fill}{fg_overlay}{ch}"
        elif shimmer_phase is not None and ch == " ":
            dot = _static_dot(i, seed)
            if dot is None:
                # Blank sky — stays empty. A star NEVER spawns in a bare cell;
                # twinkling only happens where a star already lives, so the
                # bright flash always lands ON a dot, not beside it.
                result += f"{bg_empty}{fg_overlay} "
            elif _sparkle_hash(i, shimmer_phase + seed) % _STAR_RARITY == 0:
                # This star flares bright IN PLACE — same cell as its resting
                # dot — blooming from ⋆ to a brighter ✦/✧ for this tick.
                h = _sparkle_hash(i, shimmer_phase + seed)
                result += f"{bg_empty}{star}{_STAR_GLYPHS[(h >> 4) & 1]}"
            else:
                dcol = dim_bright if _dot_is_bright(i, seed) else dim
                result += f"{bg_empty}{dcol}{dot}"          # resting faint star
        else:
            result += f"{bg_empty}{fg_overlay}{ch}"
    result += RESET
    return result


def _build_dimension(label, pct, severity_color, use_color,
                     warning_threshold, critical_threshold, theme,
                     shimmer_phase=None):
    mute = _fg(theme.mute)
    if pct is not None:
        bar = build_battery_bar(pct, use_color=use_color, theme=theme,
                                warning_threshold=warning_threshold,
                                critical_threshold=critical_threshold,
                                shimmer_phase=shimmer_phase,
                                seed=_field_seed(label))
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


# ── language-segment helpers ──

_LANGUAGE_OVERRIDES = {"Chinese": "ZH", "Japanese": "JA"}


def _language_code(language):
    return _LANGUAGE_OVERRIDES.get(language, language[:2].upper())


def _language_trend(estimates):
    if not isinstance(estimates, list) or len(estimates) < 2:
        return "→"
    try:
        previous = float(estimates[-2].get("band"))
        current = float(estimates[-1].get("band"))
    except (AttributeError, TypeError, ValueError):
        return "→"
    if current > previous:
        return "↑"
    if current < previous:
        return "↓"
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
    if minutes_to_reset <= 1:
        return " \U0001f389"
    if minutes_to_reset <= 10:
        return " ✨"
    if minutes_to_reset <= 30:
        return " ⚡"
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
    shimmer_phase=None,
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
                              warning_threshold, critical_threshold, theme,
                              shimmer_phase=shimmer_phase)
    dim_5h += colorize(f"⏰{reset_time}{countdown_emoji}", color_5h, use_color)
    parts = [dim_5h]

    dim_7d = _build_dimension("7d", weekly_pct, color_7d, use_color,
                              warning_threshold, critical_threshold, theme,
                              shimmer_phase=shimmer_phase)
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
