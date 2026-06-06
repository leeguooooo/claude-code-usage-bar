from claude_statusbar.styles import render_mode_line
from claude_statusbar.themes import get_theme
from claude_statusbar.config import StatusbarConfig

THEME = get_theme("graphite")


def test_full_line_no_color():
    s = render_mode_line(effort="high", thinking=True, fast=False,
                         style="default", theme=THEME, use_color=False)
    assert s == "⚙ effort:high · think:on · fast:off · style:default"


def test_thinking_and_fast_booleans():
    s = render_mode_line(effort="low", thinking=False, fast=True,
                         style="", theme=THEME, use_color=False)
    assert s == "⚙ effort:low · think:off · fast:on"


def test_missing_fields_dropped():
    # Only effort known (older Claude Code) → just that segment.
    assert render_mode_line(effort="medium", theme=THEME, use_color=False) == "⚙ effort:medium"


def test_empty_when_nothing_known():
    assert render_mode_line(theme=THEME, use_color=False) == ""


def test_color_output_is_ansi_clean_when_off():
    s = render_mode_line(effort="high", thinking=True, fast=True,
                         style="explanatory", theme=THEME, use_color=False)
    assert "\033[" not in s


def test_show_mode_default_on():
    assert StatusbarConfig().show_mode is True
