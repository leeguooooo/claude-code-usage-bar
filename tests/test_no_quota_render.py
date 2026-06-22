"""Render tests for no-quota-mode layout (option A).

In no-quota mode the classic line drops the 5h/7d quota battery bars and
promotes the context window to its own battery bar (label "ctx"), colored on
claude-hud's context thresholds (warn 70 / crit 85 on used%), followed by the
model name. The activity tail is appended by styles.render as usual.
"""

from claude_statusbar import progress


def _plain(**kw):
    kw.setdefault("use_color", False)
    kw.setdefault("msgs_pct", None)
    kw.setdefault("weekly_pct", None)
    kw.setdefault("reset_time", "--")
    kw.setdefault("model", "Opus 4.8")
    return progress.format_status_line(tkns_pct=None, **kw)


def test_no_quota_renders_context_bar_not_quota_bars():
    out = _plain(ctx_pct=35, no_quota=True)
    assert "ctx[" in out          # context promoted to its own bar
    assert "35%" in out
    assert "5h[" not in out       # quota bars gone
    assert "7d[" not in out
    assert "Opus 4.8" in out


def test_no_quota_off_keeps_quota_bars():
    """Default (no_quota=False) is unchanged: 5h/7d bars still render."""
    out = _plain(msgs_pct=42, weekly_pct=18, reset_time="1h59m", ctx_pct=35)
    assert "5h[" in out
    assert "7d[" in out
    assert "ctx[" not in out


def test_no_quota_context_color_uses_claude_hud_thresholds():
    """Context bar colors on 70/85 (claude-hud), not cs's 30/70 comfort band:
    50% context is calm green, not warning."""
    out = progress.format_status_line(
        msgs_pct=None, tkns_pct=None, reset_time="--", model="Opus 4.8",
        weekly_pct=None, ctx_pct=50, no_quota=True, use_color=True,
        theme=progress.get_theme("graphite"),
    )
    theme = progress.get_theme("graphite")
    ok = progress._fg(theme.s_ok)
    warn = progress._fg(theme.s_warn)
    # 50% used → green (below the 70 warn line), never yellow.
    assert ok in out
    # the ctx label itself must not be painted warning at 50%
    assert f"{warn}ctx" not in out


def test_no_quota_missing_context_shows_placeholder():
    """Worst case: relay strips context_window too → honest --% placeholder,
    still no quota bars."""
    out = _plain(ctx_pct=None, no_quota=True)
    assert "ctx[" in out
    assert "--%" in out
    assert "5h[" not in out


# --- capsule / hairline no-quota layouts (styles.py) ---
from claude_statusbar import styles


def test_capsule_no_quota_shows_ctx_pill_not_quota():
    out = styles.render_capsule(
        msgs_pct=None, weekly_pct=None, reset_5h="--", reset_7d="",
        model="Opus 4.8", ctx_pct=35, no_quota=True, use_color=False,
    )
    assert "CTX" in out or "ctx" in out
    assert "35%" in out
    assert "5H" not in out
    assert "7D" not in out
    assert "Opus 4.8" in out


def test_hairline_no_quota_shows_ctx_not_quota():
    out = styles.render_hairline(
        msgs_pct=None, weekly_pct=None, reset_5h="--", reset_7d="",
        model="Opus 4.8", ctx_pct=35, no_quota=True, use_color=False,
    )
    assert "ctx" in out
    assert "35%" in out
    assert "5h" not in out
    assert "7d" not in out
    assert "Opus 4.8" in out


def test_capsule_no_quota_off_unchanged():
    out = styles.render_capsule(
        msgs_pct=42, weekly_pct=18, reset_5h="1h", reset_7d="2d",
        model="Opus 4.8", ctx_pct=35, use_color=False,
    )
    assert "5H" in out and "7D" in out
