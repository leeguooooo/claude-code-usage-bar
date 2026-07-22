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


def test_preview_includes_cache_and_cost_segments_in_output(monkeypatch):
    """v3.3.1 fix: preview must show cache + $ cost so users can see what
    those segments look like across themes.

    Force the demo dataset: preview prefers the machine's real cached stdin
    (~/.cache/claude-statusbar/last_stdin.json) when present, which may legitimately
    have no warm cache or session cost (e.g. 5h=0%/7d=0% with no active turn) — so
    the segments would be absent for reasons unrelated to rendering. The demo data
    is exactly the fixture that guarantees both segments, which is what this test is
    about."""
    monkeypatch.setattr(preview, "_real_data", lambda: None)
    rc, out = _run(style_filter="capsule", theme_filter="graphite")
    assert "cache " in out, "preview must render cache segment"
    assert "$" in out, "preview must render cost segment"


# ---------------------------------------------------------------------------
# Codex-flagged: argv parsing must accept both `--theme nord` and `--theme=nord`
# ---------------------------------------------------------------------------
def _run_cli(argv_tail):
    """Drive cs preview through cli.main() to exercise the actual argv parser
    (rather than calling preview.run() directly, which bypasses the parser)."""
    import io
    import sys as _sys
    from claude_statusbar import cli
    saved_argv = _sys.argv
    _sys.argv = ["cs"] + argv_tail
    buf = io.StringIO()
    err = io.StringIO()
    saved_out, saved_err = _sys.stdout, _sys.stderr
    _sys.stdout = buf
    _sys.stderr = err
    try:
        rc = cli.main()
    finally:
        _sys.argv = saved_argv
        _sys.stdout = saved_out
        _sys.stderr = saved_err
    return rc, buf.getvalue(), err.getvalue()


def test_preview_accepts_theme_equals_form():
    """`cs preview --theme=nord` must filter same as `--theme nord`. The
    equals form is a standard shell idiom; silent fall-through to all-21
    rows surprises users."""
    rc, out, _ = _run_cli(["preview", "--no-color", "--theme=nord"])
    assert rc == 0
    # Other themes must NOT appear as left-bracket labels.
    for absent in ("twilight", "linen", "dracula", "sakura", "mono"):
        assert f"[{absent}" not in out, f"--theme= filter leaked {absent!r}"
    assert "[nord" in out


def test_preview_accepts_style_equals_form():
    rc, out, _ = _run_cli(["preview", "--no-color", "--style=hairline"])
    assert rc == 0
    assert "HAIRLINE" in out
    assert "CLASSIC" not in out and "CAPSULE" not in out


def test_preview_rejects_flag_without_value():
    """`cs preview --theme` (no value) must error out, not silently render
    all themes — that pattern would surprise the user."""
    rc, out, err = _run_cli(["preview", "--no-color", "--theme"])
    assert rc == 2
    assert "requires a value" in err


def test_preview_rejects_flag_followed_by_another_flag():
    """`cs preview --theme --no-color` must NOT treat '--no-color' as the theme
    name. Take it as 'missing value' and error out."""
    rc, out, err = _run_cli(["preview", "--theme", "--no-color"])
    assert rc == 2
    assert "requires a value" in err


def test_preview_classic_varies_by_theme(capsys, monkeypatch):
    """After per-segment color management lands, classic must respect
    the active theme — different themes produce different ANSI."""
    from claude_statusbar import preview as preview_mod

    # Force demo data so the test doesn't depend on a live cache file.
    monkeypatch.setattr(preview_mod, "_real_data", lambda: None)

    preview_mod.run(use_color=True, theme_filter="graphite", style_filter="classic")
    out_g = capsys.readouterr().out

    preview_mod.run(use_color=True, theme_filter="linen", style_filter="classic")
    out_l = capsys.readouterr().out

    # Both renders produce non-empty output containing the model.
    assert "Opus" in out_g and "Opus" in out_l
    # The two themes must produce different ANSI (the regression).
    assert out_g != out_l
