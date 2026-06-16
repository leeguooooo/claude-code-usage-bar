"""Rate-limit windows (5h / 7d) color by their `→NN%` projection.

The bar's fill LENGTH and printed % still track current usage; only the color
follows where usage is HEADED. With no projection yet, the window falls back to
current usage on the configured comfort thresholds (legacy behavior).
"""

from claude_statusbar.progress import (
    PROJECTION_CRITICAL_THRESHOLD,
    PROJECTION_WARNING_THRESHOLD,
    format_status_line,
    projection_pct,
    window_severity_rgb,
)
from claude_statusbar.styles import render
from claude_statusbar.themes import get_theme

THEME = get_theme("graphite")


# ── projection_pct ──────────────────────────────────────────────────────────
def test_projection_pct_parses_value():
    assert projection_pct("→96%") == 96.0


def test_projection_pct_placeholder_is_none():
    assert projection_pct("→--") is None


def test_projection_pct_empty_and_none_are_none():
    assert projection_pct("") is None
    assert projection_pct(None) is None


def test_projection_pct_junk_is_none():
    assert projection_pct("→??%") is None


# ── window_severity_rgb: projection drives, cap is the red line ──────────────
def test_projection_low_is_green_even_when_current_higher():
    # current 30% (would be warn on configured 30/70) but headed only to 30%.
    assert window_severity_rgb(30, "→30%", THEME) == THEME.s_ok


def test_projection_near_cap_is_warn():
    # current only 24% but projected 96% → yellow.
    assert window_severity_rgb(24, "→96%", THEME) == THEME.s_warn


def test_projection_at_warn_boundary_is_warn():
    assert window_severity_rgb(5, "→80%", THEME) == THEME.s_warn


def test_projection_just_below_warn_is_green():
    assert window_severity_rgb(5, "→79%", THEME) == THEME.s_ok


def test_projection_at_cap_is_hot():
    # chip is clamped to 100 upstream, so ≥100% projection arrives as →100%.
    assert window_severity_rgb(50, "→100%", THEME) == THEME.s_hot


def test_projection_thresholds_are_80_100():
    assert PROJECTION_WARNING_THRESHOLD == 80.0
    assert PROJECTION_CRITICAL_THRESHOLD == 100.0


# ── fallback to current usage when no projection ────────────────────────────
def test_no_projection_falls_back_to_current_usage():
    # →-- placeholder: legacy semantics on configured 30/70 thresholds.
    assert window_severity_rgb(75, "→--", THEME) == THEME.s_hot   # 75 ≥ 70
    assert window_severity_rgb(30, "→--", THEME) == THEME.s_warn  # 30 ≥ 30
    assert window_severity_rgb(10, "→--", THEME) == THEME.s_ok    # 10 < 30


def test_no_projection_respects_custom_thresholds():
    assert window_severity_rgb(50, "", THEME,
                               warning_threshold=40,
                               critical_threshold=60) == THEME.s_warn


def test_nothing_to_color_returns_none():
    assert window_severity_rgb(None, "", THEME) is None
    assert window_severity_rgb(None, "→--", THEME) is None


# ── end-to-end: the colored render differs from current-usage coloring ──────
def _segments(line, use_color=True, **extra):
    base = dict(
        msgs_pct=24, tkns_pct=None, reset_time="4h54m", model="Opus 4.8",
        weekly_pct=24, reset_time_7d="4d18h", theme=THEME, use_color=use_color,
    )
    base.update(extra)
    return format_status_line(**base)


def test_classic_bar_fill_length_tracks_current_not_projection():
    # 7d projected 96% but the bar's printed number stays at current 24%;
    # the 96% only appears as the separate `→96%` projection chip.
    line = _segments(None, use_color=False, projection_7d="→96%")
    # bar shows current usage (24%) twice — once per window — plus the chip.
    assert line.count("24%") == 2  # both bars labeled with current usage
    assert "→96%" in line          # projection shown as a chip, not the bar
    assert "96%░" not in line      # bar is NOT filled/labeled to the projection


def test_classic_low_current_high_projection_uses_warn_color():
    warn = f"\033[38;2;{THEME.s_warn[0]};{THEME.s_warn[1]};{THEME.s_warn[2]}m"
    ok = f"\033[38;2;{THEME.s_ok[0]};{THEME.s_ok[1]};{THEME.s_ok[2]}m"
    # current 24% → without projection it'd be green; →96% should make it warn.
    line = _segments(None, projection_7d="→96%")
    assert warn in line
    # and a low-projection 5h stays green
    line2 = _segments(None, projection_5h="→10%", projection_7d="→10%")
    assert ok in line2


def test_all_three_styles_accept_projection_kwargs():
    common = dict(
        msgs_pct=24, weekly_pct=24, reset_5h="4h54m", reset_7d="4d18h",
        model="Opus 4.8", theme=THEME, projection_5h="→30%",
        projection_7d="→96%", ctx_pct=51,
    )
    for style in ("classic", "capsule", "hairline"):
        out = render(style, **common)
        warn = f"38;2;{THEME.s_warn[0]};{THEME.s_warn[1]};{THEME.s_warn[2]}m"
        assert warn in out  # the →96% 7d window is yellow in every style
