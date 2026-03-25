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


def format_status_line(
    msgs_pct: Optional[float],
    tkns_pct: Optional[float],
    reset_time: str,
    model: str,
    bypass: bool = False,
    use_color: bool = True,
) -> str:
    """Build the complete status bar string.

    Each progress bar is colored independently. Surrounding text (labels,
    separators, timer, model) uses the highest severity color.
    """
    # Overall color for text/separators = max severity
    overall_color = color_for_percent(max(msgs_pct or 0, tkns_pct or 0))

    # Messages bar
    if msgs_pct is not None:
        m_bar = build_bar(msgs_pct)
        m_label = "100%+" if msgs_pct > 100 else f"{msgs_pct:.0f}%"
        m_color = color_for_percent(msgs_pct)
    else:
        m_bar = EMPTY * 10
        m_label = "--%"
        m_color = GREEN

    # Tokens bar
    if tkns_pct is not None:
        t_bar = build_bar(tkns_pct)
        t_label = "100%+" if tkns_pct > 100 else f"{tkns_pct:.0f}%"
        t_color = color_for_percent(tkns_pct)
    else:
        t_bar = EMPTY * 10
        t_label = "--%"
        t_color = GREEN

    # Build parts: bar colored by its own severity, label by overall
    msgs_part = (
        f"{colorize('[' + m_bar + ']', m_color, use_color)}"
        f" {colorize('msgs ' + m_label, overall_color, use_color)}"
    )
    tkns_part = (
        f"{colorize('[' + t_bar + ']', t_color, use_color)}"
        f" {colorize('tkns ' + t_label, overall_color, use_color)}"
    )
    time_part = colorize(f"⏰{reset_time}", overall_color, use_color)
    model_part = colorize(model, overall_color, use_color)

    parts = [msgs_part, tkns_part, time_part, model_part]
    if bypass:
        parts.append(colorize("⚠️BYPASS", RED, use_color))

    separator = colorize(" | ", overall_color, use_color)
    return separator.join(parts)
