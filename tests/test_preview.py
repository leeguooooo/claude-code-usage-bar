"""Tests for `cs preview` — the three looks side by side."""

import io
from contextlib import redirect_stdout

from claude_statusbar import preview


def _run(theme_filter=None, style_filter=None):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = preview.run(use_color=False, theme_filter=theme_filter, style_filter=style_filter)
    return rc, buf.getvalue()


def test_preview_default_renders_the_three_looks():
    rc, out = _run()
    assert rc == 0
    for label in ("AURORA（方块）", "AURORA（细线）", "CLASSIC"):
        assert label in out, f"missing heading {label!r} in preview output"
    assert "■" in out and "━" in out
    for removed in ("CAPSULE", "HAIRLINE"):
        assert removed not in out


def test_preview_style_filter_limits_output():
    rc, out = _run(style_filter="classic")
    assert rc == 0
    assert "CLASSIC" in out
    assert "AURORA" not in out


def test_preview_graphite_filter_still_accepted():
    rc, out = _run(theme_filter="graphite")
    assert rc == 0
    assert "AURORA" in out


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
    rc, out = _run(style_filter="classic", theme_filter="graphite")
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
    """`cs preview --theme=graphite` must parse same as `--theme graphite`."""
    rc, out, _ = _run_cli(["preview", "--no-color", "--theme=graphite"])
    assert rc == 0
    rc, out, _ = _run_cli(["preview", "--no-color", "--theme=nord"])
    assert rc == 2  # removed theme names are rejected, not silently ignored


def test_preview_accepts_style_equals_form():
    rc, out, _ = _run_cli(["preview", "--no-color", "--style=classic"])
    assert rc == 0
    assert "CLASSIC" in out
    assert "AURORA" not in out


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

