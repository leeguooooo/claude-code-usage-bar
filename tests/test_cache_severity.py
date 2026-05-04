"""Direct unit tests for styles._cache_severity color contract.

The styles layer detects cache state by string content (`"m"`/`"h"` ⇒ green,
otherwise yellow, `"COLD"` ⇒ red). This is implicit coupling between the
formatter (core.get_cache_age_text) and the colorizer (styles._cache_severity).
These tests pin the contract directly so a future format change can't
silently miscolor without a test failure.
"""

from claude_statusbar.styles import _cache_severity
from claude_statusbar.themes import get_theme


THEME = get_theme("graphite")


def test_cold_returns_hot_red():
    assert _cache_severity(THEME, "COLD") == THEME.s_hot


def test_sub_minute_returns_warning_yellow():
    """Sub-minute remaining renders as bare 'Ys' (no m/h) → yellow."""
    for v in ("59s", "30s", "5s", "1s", "0s"):
        assert _cache_severity(THEME, v) == THEME.s_warn, (
            f"{v!r} should map to s_warn (yellow); contract drift"
        )


def test_minute_or_hour_returns_ok_green():
    """Anything containing 'm' or 'h' is in the comfortable zone."""
    for v in ("1m00s", "4m23s", "5m", "50m", "1h", "1h59m", "2h"):
        assert _cache_severity(THEME, v) == THEME.s_ok, (
            f"{v!r} should map to s_ok (green); contract drift"
        )


def test_empty_string_falls_to_warning():
    """Defensive: empty string shouldn't reach this helper, but if it does,
    the safest default is the loud warning color (not silent green)."""
    # Empty has no 'm' or 'h' → yellow.
    assert _cache_severity(THEME, "") == THEME.s_warn
