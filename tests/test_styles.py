"""Smoke tests for the style + theme dispatch system."""

import pytest

from claude_statusbar.styles import (
    DENSITY_PAD,
    RENDERERS,
    is_known_style,
    list_styles,
    render,
)
from claude_statusbar.themes import BUILTIN_THEMES, get_theme, list_themes


SAMPLE = dict(
    msgs_pct=42, weekly_pct=18,
    reset_5h="2h47m", reset_7d="3d12h",
    model="Opus 4.7(45.0k/1.0M)",
    lang_body="EN:6.0↑",
    bypass=False,
    warning_threshold=30.0,
    critical_threshold=70.0,
)


def test_three_builtin_styles():
    assert set(list_styles()) == {"classic", "capsule", "hairline"}


def test_seven_builtin_themes():
    names = {t.name for t in list_themes()}
    assert names == {"graphite", "twilight", "linen", "nord", "dracula", "sakura", "mono"}


_ANSI_RE = __import__("re").compile(r"\033\[[0-9;]*m")


@pytest.mark.parametrize("style", list(RENDERERS))
@pytest.mark.parametrize("theme", [t.name for t in BUILTIN_THEMES])
def test_every_combination_renders(style, theme):
    """Every style × theme combination produces a non-empty string and contains
    the percentage values. Classic interleaves ANSI codes inside the battery
    bar so we assert against the ANSI-stripped form."""
    out = render(style, theme=get_theme(theme), use_color=True, **SAMPLE)
    assert out, f"{style}/{theme} produced empty output"
    plain = _ANSI_RE.sub("", out)
    assert "42" in plain
    # Hairline + capsule both honor show_weekly toggle; classic always shows it
    assert "18" in plain


@pytest.mark.parametrize("style", list(RENDERERS))
def test_no_color_strips_all_ansi(style):
    out = render(style, theme=get_theme("graphite"), use_color=False, **SAMPLE)
    assert "\033[" not in out, f"{style} leaked ANSI when use_color=False"


def test_unknown_style_falls_back_to_classic():
    """Typo in style name should not raise — Claude Code statusLine has no
    way to surface the error, so we silently render with the safe default."""
    out = render("not-a-real-style", theme=get_theme("graphite"),
                  use_color=False, **SAMPLE)
    assert out  # must not raise; must produce output


def test_unknown_kwargs_are_swallowed():
    """Renderers accept **_ignored so callers can pass style-specific args
    (countdown_emoji, density, ...) without breaking other styles."""
    render("classic", theme=get_theme("graphite"), use_color=False,
           density="cozy", show_weekly=False,
           **SAMPLE)
    render("capsule", theme=get_theme("graphite"), use_color=False,
           countdown_emoji="🌙",
           **SAMPLE)


def test_capsule_show_weekly_toggle():
    out_with = render("capsule", theme=get_theme("graphite"),
                       use_color=False, show_weekly=True, **SAMPLE)
    out_without = render("capsule", theme=get_theme("graphite"),
                          use_color=False, show_weekly=False, **SAMPLE)
    assert "7D" in out_with
    assert "7D" not in out_without


def test_density_pad_constants():
    assert DENSITY_PAD["compact"] == ""
    assert DENSITY_PAD["regular"] == " "
    assert DENSITY_PAD["cozy"] == "  "


def test_is_known_style():
    assert is_known_style("classic")
    assert is_known_style("capsule")
    assert not is_known_style("capsulee")
    assert not is_known_style("")


def test_capsule_does_not_eat_emoji_prefix():
    """Regression: prior implementation used lstrip('📚 ') which would also
    strip a literal space at the start of language data. The fix routes raw
    body strings into the renderer."""
    body = " 📚EN:6.0"  # leading space + emoji that would have triggered the bug
    out = render("capsule", theme=get_theme("graphite"),
                  use_color=False,
                  msgs_pct=42, weekly_pct=18,
                  reset_5h="2h", reset_7d="3d",
                  model="Opus 4.7", lang_body=body,
                  bypass=False, warning_threshold=30.0, critical_threshold=70.0)
    assert body in out, "language body content was mangled"
