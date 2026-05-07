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
