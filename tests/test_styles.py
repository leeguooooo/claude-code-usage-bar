"""Smoke tests for the style + theme dispatch system."""

import pytest

from claude_statusbar._display import visible_width
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
    assert set(list_styles()) == {"classic", "capsule", "hairline", "aurora"}


def test_builtin_themes():
    names = {t.name for t in list_themes()}
    assert names == {
        "graphite", "twilight", "linen", "nord", "dracula", "sakura", "mono",
        "catppuccin-mocha", "tokyo-night",
    }


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


@pytest.mark.parametrize("style", list(RENDERERS))
@pytest.mark.parametrize("use_color", [False, True])
def test_max_width_caps_every_physical_line(style, use_color):
    out = render(
        style, theme=get_theme("graphite"), use_color=use_color,
        max_width=38, cost_text="123.45", cache_age_text="COLD",
        forecast_5h="→99%", forecast_7d="→98%",
        projection_5h="→97%", projection_7d="→96%",
        fp_line_text="⚠ third-party relay warning with long action text",
        fp_line_level="warn", **SAMPLE,
    )
    assert all(visible_width(line) <= 38 for line in out.splitlines())


@pytest.mark.parametrize("style", list(RENDERERS))
def test_max_width_is_noop_when_output_already_fits(style):
    kwargs = dict(theme=get_theme("graphite"), use_color=False, **SAMPLE)
    assert render(style, **kwargs, max_width=500) == render(style, **kwargs)


@pytest.mark.parametrize("style", list(RENDERERS))
def test_context_suffix_is_complete_or_omitted(style):
    out = render(
        style, theme=get_theme("graphite"), use_color=False, max_width=34,
        cost_text="123.45", cache_age_text="COLD", **SAMPLE,
    )
    assert "45.0k/1.0M" not in out or "(45.0k/1.0M)" in out
    assert all(fragment not in out for fragment in ("(45.0k/", "45.0k/1.0…"))


def test_context_denominator_drops_before_the_whole_count():
    """A width that fits "(45.0k)" but not "(45.0k/1.0M)" keeps the count."""
    sample = dict(SAMPLE, lang_body="")  # nothing optional left to sacrifice
    full = render("capsule", theme=get_theme("graphite"), use_color=False,
                  **sample)
    width = visible_width(full.split("\n", 1)[0]) - 4  # loses "/1.0M", not more
    out = render("capsule", theme=get_theme("graphite"), use_color=False,
                 max_width=width, **sample)
    assert "(45.0k)" in out
    assert "45.0k/1.0M" not in out


def test_optional_degradation_order_is_stable(monkeypatch):
    calls = []

    def probe(**kwargs):
        calls.append((kwargs.get("cache_age_text"), kwargs.get("lang_body")))
        return "0123456789" + kwargs.get("cache_age_text", "") + kwargs.get("lang_body", "")

    monkeypatch.setitem(RENDERERS, "probe", probe)
    out = render(
        "probe", max_width=10, cache_age_text="CACHE", lang_body="LANG",
        theme=get_theme("graphite"), use_color=False,
    )
    assert calls[:3] == [("CACHE", "LANG"), ("", "LANG"), ("", "")]
    assert out == "0123456789"


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


# v3.1.0 — cost_text segment
@pytest.mark.parametrize("style", list(RENDERERS))
def test_cost_text_rendered_when_passed(style):
    out = render(style, theme=get_theme("graphite"), use_color=False,
                  msgs_pct=42, weekly_pct=18, reset_5h="2h", reset_7d="3d",
                  model="Opus 4.7", lang_body="", cost_text="0.42",
                  bypass=False, warning_threshold=30.0, critical_threshold=70.0)
    assert "0.42" in out
    assert "$" in out


@pytest.mark.parametrize("style", list(RENDERERS))
def test_cost_text_omitted_when_empty(style):
    out = render(style, theme=get_theme("graphite"), use_color=False,
                  msgs_pct=42, weekly_pct=18, reset_5h="2h", reset_7d="3d",
                  model="Opus 4.7", lang_body="", cost_text="",
                  bypass=False, warning_threshold=30.0, critical_threshold=70.0)
    assert "$" not in out


def test_cost_text_position_after_model_in_classic():
    """In classic style cost should appear after model, before language."""
    out = render("classic", theme=get_theme("graphite"), use_color=False,
                  msgs_pct=42, weekly_pct=18, reset_5h="2h", reset_7d="3d",
                  model="Opus 4.7", lang_body="EN:6.0↑", cost_text="0.42",
                  bypass=False, warning_threshold=30.0, critical_threshold=70.0)
    model_pos = out.index("Opus 4.7")
    cost_pos  = out.index("0.42")
    lang_pos  = out.index("📚")
    assert model_pos < cost_pos < lang_pos


def test_every_theme_has_pill_cost():
    """pill_cost is mandatory and distinct from pill_lang for every theme."""
    for t in BUILTIN_THEMES:
        assert hasattr(t, "pill_cost"), f"{t.name} missing pill_cost"
        assert isinstance(t.pill_cost, tuple) and len(t.pill_cost) == 3, \
            f"{t.name}.pill_cost must be an RGB 3-tuple"
        assert t.pill_cost != t.pill_lang, \
            f"{t.name}.pill_cost must differ from pill_lang (collision is the bug)"


def test_aurora_cache_text_drops_seconds_when_far():
    from claude_statusbar.styles import _aurora_cache_text
    assert _aurora_cache_text("1h00m00s") == "1h00m"
    assert _aurora_cache_text("59m12s") == "59m"
    assert _aurora_cache_text("4m23s") == "4m23s"
    assert _aurora_cache_text("42s") == "42s"
    assert _aurora_cache_text("COLD") == "COLD"


def test_aurora_plain_layout():
    from claude_statusbar.styles import render
    out = render("aurora", msgs_pct=4, weekly_pct=74, reset_5h="4h16m",
                 reset_7d="2d18h", model="Opus 5.5(70.0k/1.0M)", ctx_pct=7,
                 cache_age_text="59m12s", use_color=False)
    assert out == ("5h ━━━━━━━━━━━━  4% ⏰4h16m │ 7d ━━━━━━━━━━━━ 74% ⏰2d18h"
                   " │ Opus 5.5 ━━━━━━ 7% │ ❄ 59m")


def test_aurora_keeps_tokens_without_ctx_and_handles_stale():
    from claude_statusbar.styles import render
    out = render("aurora", msgs_pct=None, weekly_pct=None, reset_5h="",
                 reset_7d="", model="Opus 5.5(70.0k/1.0M)", quota_stale=True,
                 use_color=False)
    assert out.startswith("⟳ 5h/7d stale·restart │ Opus 5.5(70.0k/1.0M)")


def test_aurora_identity_line_layout():
    from types import SimpleNamespace
    from claude_statusbar.styles import render_identity_line_aurora
    from claude_statusbar.themes import get_theme
    info = SimpleNamespace(project_name="proj", in_git=True, branch="main",
                           detached=False, is_worktree=False, worktree_count=1,
                           worktree_name=None)
    out = render_identity_line_aurora(
        info, theme=get_theme("graphite"), dirty=True, ahead=0, behind=1,
        duration_text="4m", lines_text="+244", version_text="3.47.0",
        update_text="", use_color=False)
    assert out == "⎇ main ●↓1 │ proj │ +244 │ ⏱ 4m │ ⑂ trunk (1)"
    # Trunk marker only with other worktrees; version only when an update waits.
    info.worktree_count = 0
    out = render_identity_line_aurora(
        info, theme=get_theme("graphite"), dirty=False, lines_text="+5 -2",
        version_text="3.48.0", update_text="3.49.0", use_color=False)
    assert out == "⎇ main │ proj │ +5 −2 │ v3.48.0 ↑3.49.0"


def test_aurora_ocs_line():
    from claude_statusbar.styles import render_ocs_line_aurora
    from claude_statusbar.themes import get_theme
    out = render_ocs_line_aurora(
        "claude-b2242a10", 3,
        {"running": True, "peers": [("win", True), ("mac", False)]},
        theme=get_theme("graphite"), use_color=False)
    assert out == "ocs claude-b2242a10 │ ✉3 │ lan ● win · ● mac"


def test_graphite_ok_is_leo_green():
    from claude_statusbar.themes import get_theme
    assert get_theme("graphite").s_ok == (78, 200, 91)


def test_aurora_identity_worktree_leads():
    from types import SimpleNamespace
    from claude_statusbar.styles import render_identity_line_aurora
    from claude_statusbar.themes import get_theme
    info = SimpleNamespace(project_name="proj", in_git=True, branch="feat",
                           detached=False, is_worktree=True, worktree_count=2,
                           worktree_name="proj-wt-x")
    out = render_identity_line_aurora(info, theme=get_theme("graphite"),
                                      dirty=False, use_color=False)
    assert out.startswith("⑂ ")
    assert "trunk" not in out


def test_aurora_projection_wins_over_forecast():
    from claude_statusbar.styles import render
    out = render("aurora", msgs_pct=40, weekly_pct=10, reset_5h="2h",
                 reset_7d="3d", model="Opus", projection_5h="→80%",
                 forecast_5h="~8m", use_color=False)
    assert "→80%" in out and "~8m" not in out
    out = render("aurora", msgs_pct=40, weekly_pct=10, reset_5h="2h",
                 reset_7d="3d", model="Opus", forecast_5h="~8m",
                 use_color=False)
    assert "⚠~8m" in out
