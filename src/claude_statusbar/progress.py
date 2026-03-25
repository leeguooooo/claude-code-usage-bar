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


def _build_dimension(label: str, pct: Optional[float],
                      overall_color: str, use_color: bool) -> str:
    """Build one progress bar dimension: [████░░░░░░] label XX%"""
    if pct is not None:
        bar = build_bar(pct)
        text = "100%+" if pct > 100 else f"{pct:.0f}%"
        bar_color = color_for_percent(pct)
    else:
        bar = EMPTY * 10
        text = "--%"
        bar_color = GREEN
    return (
        f"{colorize('[' + bar + ']', bar_color, use_color)}"
        f" {colorize(label + ' ' + text, overall_color, use_color)}"
    )


def format_status_line(
    msgs_pct: Optional[float],
    tkns_pct: Optional[float],
    reset_time: str,
    model: str,
    plan: str = "",
    weekly_pct: Optional[float] = None,
    ctx_pct: Optional[float] = None,
    bypass: bool = False,
    use_color: bool = True,
) -> str:
    """Build the complete status bar string.

    Shows 5-hour window, 7-day weekly window, and context window usage.
    Each progress bar is colored independently. Surrounding text uses
    the highest severity color across all dimensions.
    """
    # Overall color = max severity across all dimensions (ctx excluded — it's per-session)
    all_pcts = [p for p in (msgs_pct, tkns_pct, weekly_pct) if p is not None]
    overall_color = color_for_percent(max(all_pcts) if all_pcts else 0)

    parts = [
        _build_dimension("5h", msgs_pct, overall_color, use_color),
        _build_dimension("7d", weekly_pct, overall_color, use_color),
    ]

    parts.append(colorize(f"⏰{reset_time}", overall_color, use_color))
    if plan:
        parts.append(colorize(plan, overall_color, use_color))
    parts.append(colorize(model, overall_color, use_color))
    if bypass:
        parts.append(colorize("⚠️BYPASS", RED, use_color))

    separator = colorize(" | ", overall_color, use_color)
    return separator.join(parts)
