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
