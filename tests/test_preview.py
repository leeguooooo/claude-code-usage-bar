"""Tests for `cs preview` — style × theme matrix renderer."""

import io
import sys
from contextlib import redirect_stdout

from claude_statusbar import preview


def _run(theme_filter=None, style_filter=None):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = preview.run(use_color=False, theme_filter=theme_filter, style_filter=style_filter)
    return rc, buf.getvalue()


def test_preview_default_renders_all_styles_and_themes():
    rc, out = _run()
    assert rc == 0
    # All 3 style headings appear
    for label in ("CLASSIC", "CAPSULE", "HAIRLINE"):
        assert label in out, f"missing style heading {label!r} in preview output"
    # All 7 theme rows appear (under capsule + hairline at minimum)
    for theme in ("graphite", "twilight", "linen", "nord", "dracula", "sakura", "mono"):
        assert theme in out, f"missing theme row {theme!r}"


def test_preview_theme_filter_limits_output():
    """`cs preview --theme nord` must show only nord rows under each style."""
    rc, out = _run(theme_filter="nord")
    assert rc == 0
    # nord must appear; the other 6 themes must NOT appear as left-bracket labels
    for absent in ("twilight", "linen", "dracula", "sakura", "mono"):
        assert f"[{absent}" not in out, f"theme filter leaked {absent!r}"
    assert "[nord" in out


def test_preview_style_filter_limits_output():
    rc, out = _run(style_filter="hairline")
    assert rc == 0
    assert "HAIRLINE" in out
    # Other style headings must not appear
    for absent in ("CLASSIC", "CAPSULE"):
        assert absent not in out, f"style filter leaked {absent!r}"


def test_preview_combined_filter_renders_one_combo():
    rc, out = _run(style_filter="capsule", theme_filter="dracula")
    assert rc == 0
    assert "CAPSULE" in out
    assert "[dracula" in out
    # Only this combo — neither HAIRLINE nor other themes
    assert "HAIRLINE" not in out
    assert "[graphite" not in out


def test_preview_unknown_theme_returns_error():
    rc, out = _run(theme_filter="not-a-real-theme")
    assert rc == 2
    assert "unknown theme" in out


def test_preview_unknown_style_returns_error():
    rc, out = _run(style_filter="not-a-real-style")
    assert rc == 2
    assert "unknown style" in out


def test_preview_includes_cache_and_cost_segments_in_output():
    """v3.3.1 fix: preview must show cache + $ cost so users can see what
    those segments look like across themes."""
    rc, out = _run(style_filter="capsule", theme_filter="graphite")
    assert "cache " in out, "preview must render cache segment"
    assert "$" in out, "preview must render cost segment"
