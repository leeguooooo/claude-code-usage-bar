"""Progress bar rendering for the status bar. Pure functions, no I/O."""

from typing import Optional

FILL = "█"
EMPTY = "░"


def build_bar(percent: float, width: int = 10) -> str:
    """Render a progress bar string.

    Uses half-up rounding (not Python's banker's rounding) to avoid
    surprising behavior at .5 boundaries.

    Args:
        percent: 0-100+ (clamped to 0-100 for display).
        width: number of characters in the bar.

    Returns:
        String of width characters using FILL and EMPTY.
    """
    clamped = max(0.0, min(percent, 100.0))
    filled = int(clamped / 100 * width + 0.5)  # half-up rounding
    # At least 1 filled block when percent > 0
    if percent > 0 and filled == 0:
        filled = 1
    return FILL * filled + EMPTY * (width - filled)


GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"


def color_for_percent(percent: float) -> str:
    """Return ANSI color code based on threshold."""
    if percent >= 70:
        return RED
    if percent >= 30:
        return YELLOW
    return GREEN


def colorize(text: str, color: str, use_color: bool = True) -> str:
    """Wrap text in ANSI color codes. No-op when use_color is False."""
    if not use_color:
        return text
    return f"{color}{text}{RESET}"
