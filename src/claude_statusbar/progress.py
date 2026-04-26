"""Progress bar rendering for the status bar. Pure functions, no I/O."""

import json
from pathlib import Path
from typing import Optional
from claude_statusbar import __version__

FILL = "█"
EMPTY = "░"

# Foreground colors
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"

# Background colors
BG_GREEN = "\033[42m"
BG_YELLOW = "\033[43m"
BG_RED = "\033[41m"
BG_GRAY = "\033[100m"  # bright black (dark gray)
FG_WHITE = "\033[97m"
FG_BLACK = "\033[30m"
DIM = "\033[2m"  # dim/faint text

DEFAULT_WARNING_THRESHOLD = 30.0
DEFAULT_CRITICAL_THRESHOLD = 70.0


def normalize_thresholds(
    warning_threshold: Optional[float] = None,
    critical_threshold: Optional[float] = None,
) -> tuple[float, float]:
    """Validate and normalize warning/critical thresholds."""
    warning = (
        DEFAULT_WARNING_THRESHOLD
        if warning_threshold is None
        else float(warning_threshold)
    )
    critical = (
        DEFAULT_CRITICAL_THRESHOLD
        if critical_threshold is None
        else float(critical_threshold)
    )

    if not 0 <= warning < critical <= 100:
        raise ValueError(
            "Thresholds must satisfy 0 <= warning < critical <= 100."
        )

    return warning, critical


def build_bar(percent: float, width: int = 10) -> str:
    """Render a plain progress bar (used when color is off)."""
    clamped = max(0.0, min(percent, 100.0))
    filled = int(clamped / 100 * width + 0.5)
    if percent > 0 and filled == 0:
        filled = 1
    return FILL * filled + EMPTY * (width - filled)


def build_battery_bar(
    percent: float,
    width: int = 10,
    use_color: bool = True,
    warning_threshold: Optional[float] = None,
    critical_threshold: Optional[float] = None,
) -> str:
    """Render an iPhone-style battery bar with percentage embedded via background colors.

    Each character gets a colored background (filled) or gray background (empty),
    with the percentage text centered on top.
    """
    clamped = max(0.0, min(percent, 100.0))
    filled = int(clamped / 100 * width + 0.5)
    if percent > 0 and filled == 0:
        filled = 1

    # Build the text to overlay
    if percent > 100:
        text = "MAX"
    else:
        text = f"{percent:.0f}%"

    # Center text in the bar, pad with spaces
    padded = text.center(width)

    if not use_color:
        # No color: use block characters with text overlay
        result = ""
        for i, ch in enumerate(padded):
            if ch == " ":
                result += FILL if i < filled else EMPTY
            else:
                result += ch
        return result

    # Color mode: use background colors per character
    bg_fill = bg_for_percent(
        percent,
        warning_threshold=warning_threshold,
        critical_threshold=critical_threshold,
    )
    result = ""
    for i, ch in enumerate(padded):
        if i < filled:
            result += f"{bg_fill}{FG_WHITE}{ch}"
        else:
            result += f"{BG_GRAY}{FG_WHITE}{ch}"
    result += RESET
    return result


def color_for_percent(
    percent: float,
    warning_threshold: Optional[float] = None,
    critical_threshold: Optional[float] = None,
) -> str:
    """Return ANSI foreground color code based on threshold."""
    warning, critical = normalize_thresholds(warning_threshold, critical_threshold)
    if percent >= critical:
        return RED
    if percent >= warning:
        return YELLOW
    return GREEN


def bg_for_percent(
    percent: float,
    warning_threshold: Optional[float] = None,
    critical_threshold: Optional[float] = None,
) -> str:
    """Return ANSI background color code based on threshold."""
    warning, critical = normalize_thresholds(warning_threshold, critical_threshold)
    if percent >= critical:
        return BG_RED
    if percent >= warning:
        return BG_YELLOW
    return BG_GREEN


def colorize(text: str, color: str, use_color: bool = True) -> str:
    """Wrap text in ANSI color codes. No-op when use_color is False."""
    if not use_color:
        return text
    return f"{color}{text}{RESET}"


def _build_dimension(label: str, pct: Optional[float],
                      overall_color: str, use_color: bool,
                      warning_threshold: Optional[float],
                      critical_threshold: Optional[float]) -> str:
    """Build one progress bar dimension: label[battery_bar]"""
    if pct is not None:
        bar = build_battery_bar(
            pct,
            use_color=use_color,
            warning_threshold=warning_threshold,
            critical_threshold=critical_threshold,
        )
    else:
        if use_color:
            bar = f"{BG_GRAY}{FG_WHITE}" + "--%".center(10) + RESET
        else:
            bar = EMPTY * 3 + "--%" + EMPTY * 4
    return (
        f"{colorize(label, overall_color, use_color)}"
        f"[{bar}]"
    )


_LANGUAGE_OVERRIDES: dict[str, str] = {
    "Chinese": "ZH",
    "Japanese": "JA",
}


def _language_code(language: str) -> str:
    return _LANGUAGE_OVERRIDES.get(language, language[:2].upper())


def _language_trend(estimates: object) -> str:
    if not isinstance(estimates, list) or len(estimates) < 2:
        return "→"
    try:
        previous = float(estimates[-2].get("band"))  # type: ignore[union-attr]
        current = float(estimates[-1].get("band"))   # type: ignore[union-attr]
    except (AttributeError, TypeError, ValueError):
        return "→"
    if current > previous:
        return "↑"
    if current < previous:
        return "↓"
    return "→"


def _coach_enabled(config_path: str = "~/.claude/language-coach.json") -> bool:
    """Return True only when the language-coach plugin is installed and enabled."""
    try:
        cfg = json.loads(Path(config_path).expanduser().read_text(encoding="utf-8"))
        return bool(cfg.get("enabled", False))
    except (OSError, json.JSONDecodeError, ValueError):
        return False


# Hard cap on languages shown in the status bar. A bloated or malicious
# language-progress.json would otherwise let the segment expand indefinitely
# and push the rest of the line off-screen.
MAX_LANGUAGES = 4


def format_language_body(progress_path: str) -> str:
    """Return only the body of the language segment (e.g. 'EN:6.0↑ JA:5.0→'),
    without emoji or color codes. Empty string when disabled or missing."""
    if not _coach_enabled():
        return ""
    path = Path(progress_path).expanduser()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(payload, dict):
        return ""

    parts: list[str] = []
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


def format_language_segment(progress_path: str, use_color: bool = True) -> str:
    """Backwards-compatible wrapper used by the classic style.

    Returns a colored '📚 EN:6.0↑ JA:5.0→' string, or empty when disabled.
    New styles should call format_language_body and add their own emoji + color.
    """
    body = format_language_body(progress_path)
    if not body:
        return ""
    return colorize(f"📚 {body}", GREEN, use_color)


def format_status_line(
    msgs_pct: Optional[float],
    tkns_pct: Optional[float],
    reset_time: str,
    model: str,
    weekly_pct: Optional[float] = None,
    reset_time_7d: str = "",
    ctx_pct: Optional[float] = None,
    bypass: bool = False,
    use_color: bool = True,
    pet_text: str = "",
    countdown_emoji: str = "",
    warning_threshold: Optional[float] = None,
    critical_threshold: Optional[float] = None,
    lang_text: str = "",
) -> str:
    """Build the complete status bar string.

    Shows 5-hour window, 7-day weekly window, and context window usage.
    Each progress bar is colored independently. Surrounding text uses
    the highest severity color across all dimensions.
    """
    # Overall color = max severity across all dimensions (ctx excluded — it's per-session)
    all_pcts = [p for p in (msgs_pct, tkns_pct, weekly_pct) if p is not None]
    warning_threshold, critical_threshold = normalize_thresholds(
        warning_threshold, critical_threshold
    )
    overall_color = color_for_percent(
        max(all_pcts) if all_pcts else 0,
        warning_threshold=warning_threshold,
        critical_threshold=critical_threshold,
    )

    # 5h dimension with its reset time + countdown emoji
    dim_5h = _build_dimension(
        "5h",
        msgs_pct,
        overall_color,
        use_color,
        warning_threshold,
        critical_threshold,
    )
    dim_5h += colorize(f"⏰{reset_time}{countdown_emoji}", overall_color, use_color)
    parts = [dim_5h]

    # 7d dimension with its reset time
    dim_7d = _build_dimension(
        "7d",
        weekly_pct,
        overall_color,
        use_color,
        warning_threshold,
        critical_threshold,
    )
    if reset_time_7d:
        dim_7d += colorize(f"⏰{reset_time_7d}", overall_color, use_color)
    parts.append(dim_7d)
    parts.append(colorize(model, overall_color, use_color))
    if lang_text:
        parts.append(lang_text)
    if bypass:
        parts.append(colorize("⚠️BYPASS", RED, use_color))

    if pet_text:
        parts.append(colorize(pet_text, overall_color, use_color))

    separator = colorize(" | ", overall_color, use_color)
    return separator.join(parts)
