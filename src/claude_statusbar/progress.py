"""Progress bar rendering for the status bar. Pure functions, no I/O."""

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


def build_bar(percent: float, width: int = 10) -> str:
    """Render a plain progress bar (used when color is off)."""
    clamped = max(0.0, min(percent, 100.0))
    filled = int(clamped / 100 * width + 0.5)
    if percent > 0 and filled == 0:
        filled = 1
    return FILL * filled + EMPTY * (width - filled)


def build_battery_bar(percent: float, width: int = 10, use_color: bool = True) -> str:
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
    bg_fill = bg_for_percent(percent)
    result = ""
    for i, ch in enumerate(padded):
        if i < filled:
            result += f"{bg_fill}{FG_WHITE}{ch}"
        else:
            result += f"{BG_GRAY}{FG_WHITE}{ch}"
    result += RESET
    return result


def color_for_percent(percent: float) -> str:
    """Return ANSI foreground color code based on threshold."""
    if percent >= 70:
        return RED
    if percent >= 30:
        return YELLOW
    return GREEN


def bg_for_percent(percent: float) -> str:
    """Return ANSI background color code based on threshold."""
    if percent >= 70:
        return BG_RED
    if percent >= 30:
        return BG_YELLOW
    return BG_GREEN


def colorize(text: str, color: str, use_color: bool = True) -> str:
    """Wrap text in ANSI color codes. No-op when use_color is False."""
    if not use_color:
        return text
    return f"{color}{text}{RESET}"


def _build_dimension(label: str, pct: Optional[float],
                      overall_color: str, use_color: bool) -> str:
    """Build one progress bar dimension: label[battery_bar]"""
    if pct is not None:
        bar = build_battery_bar(pct, use_color=use_color)
    else:
        if use_color:
            bar = f"{BG_GRAY}{FG_WHITE}" + "--%".center(10) + RESET
        else:
            bar = EMPTY * 3 + "--%" + EMPTY * 4
    return (
        f"{colorize(label, overall_color, use_color)}"
        f"[{bar}]"
    )


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
) -> str:
    """Build the complete status bar string.

    Shows 5-hour window, 7-day weekly window, and context window usage.
    Each progress bar is colored independently. Surrounding text uses
    the highest severity color across all dimensions.
    """
    # Overall color = max severity across all dimensions (ctx excluded — it's per-session)
    all_pcts = [p for p in (msgs_pct, tkns_pct, weekly_pct) if p is not None]
    overall_color = color_for_percent(max(all_pcts) if all_pcts else 0)

    # 5h dimension with its reset time + countdown emoji
    dim_5h = _build_dimension("5h", msgs_pct, overall_color, use_color)
    dim_5h += colorize(f"⏰{reset_time}{countdown_emoji}", overall_color, use_color)
    parts = [dim_5h]

    # 7d dimension with its reset time
    dim_7d = _build_dimension("7d", weekly_pct, overall_color, use_color)
    if reset_time_7d:
        dim_7d += colorize(f"⏰{reset_time_7d}", overall_color, use_color)
    parts.append(dim_7d)
    parts.append(colorize(model, overall_color, use_color))
    if bypass:
        parts.append(colorize("⚠️BYPASS", RED, use_color))

    if pet_text:
        parts.append(colorize(pet_text, overall_color, use_color))

    separator = colorize(" | ", overall_color, use_color)
    return separator.join(parts)
