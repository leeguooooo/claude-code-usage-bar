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


def test_effort_color_tiers():
    from claude_statusbar.styles import _effort_color, _fg
    warn = _fg(THEME.s_warn); mute = _fg(THEME.mute); ink = _fg(THEME.ink)
    assert _effort_color("xhigh", THEME) == warn
    assert _effort_color("max", THEME) == warn
    assert _effort_color("ultracode", THEME) == warn
    assert _effort_color("low", THEME) == mute
    assert _effort_color("auto", THEME) == mute
    assert _effort_color("medium", THEME) == ink
    assert _effort_color("high", THEME) == ink
    assert _effort_color("brand-new-level", THEME) == ink   # unknown → neutral


def _distinct_fg(s):
    import re
    return set(re.findall(r"38;2;\d+;\d+;\d+", s))


def test_top_tier_effort_gets_gradient():
    for lv in ("xhigh", "max", "ultracode"):
        s = render_mode_line(effort=lv, thinking=True, fast=False,
                             style="default", theme=THEME, use_color=True)
        assert len(_distinct_fg(s)) > 5, f"{lv} should flow a multi-colour gradient"


def test_gradient_applies_to_any_effort():
    # Consistent: gradient is on for every effort tier (not just top), so the
    # line never jarringly switches between gradient and plain.
    for lv in ("low", "medium", "high", "auto"):
        s = render_mode_line(effort=lv, thinking=True, fast=False,
                             style="default", theme=THEME, use_color=True)
        assert len(_distinct_fg(s)) > 5, f"{lv} should also get the gradient"


def test_gradient_can_be_disabled():
    s = render_mode_line(effort="ultracode", thinking=True, theme=THEME,
                         use_color=True, gradient=False)
    assert len(_distinct_fg(s)) <= 3


def test_gradient_is_static_and_deterministic():
    # Static (not animated): identical output across calls, a single left→right
    # sweep that starts at the palette's first stop (pink for ultracode).
    a = render_mode_line(effort="ultracode", thinking=True, theme=THEME, use_color=True)
    b = render_mode_line(effort="ultracode", thinking=True, theme=THEME, use_color=True)
    assert a == b
    assert a.startswith("\033[38;2;236;114;179m")   # first char = pink stop
    assert len(_distinct_fg(a)) > 5


def test_gradient_no_color_is_plain():
    s = render_mode_line(effort="ultracode", thinking=True, theme=THEME, use_color=False)
    assert "\033[" not in s and s == "⚙ effort:ultracode · think:on"


def test_mode_gradient_config_default_on():
    assert StatusbarConfig().mode_gradient is True


def test_effort_tiers_have_distinct_gradients():
    # high vs the top tiers must look clearly different (the whole point).
    first = {}
    for lv in ("low", "medium", "high", "xhigh", "max", "ultracode"):
        s = render_mode_line(effort=lv, thinking=True, theme=THEME, use_color=True)
        import re
        first[lv] = re.findall(r"38;2;\d+;\d+;\d+", s)[0]
    assert first["high"] != first["ultracode"]
    assert len(set(first.values())) == len(first)   # all six tiers distinct
