"""Per-segment color management tests for the classic style.

Every numeric segment (5h, 7d, context) colors itself by its own pct.
No segment's color leaks into another. The | separator and [ ] / ( )
brackets are always theme.mute so they don't carry severity.
"""
import re
from claude_statusbar.progress import format_status_line, _fg
from claude_statusbar.themes import get_theme

GRAPHITE = get_theme("graphite")
ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def _ansi_for(rgb):
    return f"\033[38;2;{rgb[0]};{rgb[1]};{rgb[2]}m"


def test_per_segment_severity_isolation():
    """5h calm, 7d warning: separator + brackets stay mute,
    no warning ANSI appears around the 5h segment."""
    line = format_status_line(
        msgs_pct=10, tkns_pct=None, reset_time="2h00m",
        weekly_pct=50, reset_time_7d="3d00h",
        model="Opus 4.7", ctx_pct=None,
        theme=GRAPHITE, use_color=True,
    )
    s_ok = _ansi_for(GRAPHITE.s_ok)
    s_warn = _ansi_for(GRAPHITE.s_warn)
    mute = _ansi_for(GRAPHITE.mute)
    five_h_chunk = line.split("|")[0]
    assert s_ok in five_h_chunk
    assert s_warn not in five_h_chunk
    seven_d_chunk = line.split("|")[1]
    assert s_warn in seven_d_chunk
    assert mute in line


def test_ctx_pct_critical_colors_model():
    """ctx_pct=85 paints the model block s_hot even when 5h/7d are calm."""
    line = format_status_line(
        msgs_pct=10, tkns_pct=None, reset_time="2h00m",
        weekly_pct=10, reset_time_7d="3d00h",
        model="Opus 4.7(900k/1M)", ctx_pct=85,
        theme=GRAPHITE, use_color=True,
    )
    s_hot = _ansi_for(GRAPHITE.s_hot)
    model_chunk = line.split("|")[2]
    assert s_hot in model_chunk


def test_ctx_pct_none_uses_theme_ink():
    """ctx_pct=None means model text is neutral (theme.ink), no severity."""
    line = format_status_line(
        msgs_pct=10, tkns_pct=None, reset_time="2h00m",
        weekly_pct=10, reset_time_7d="3d00h",
        model="Opus 4.7", ctx_pct=None,
        theme=GRAPHITE, use_color=True,
    )
    ink = _ansi_for(GRAPHITE.ink)
    s_hot = _ansi_for(GRAPHITE.s_hot)
    s_warn = _ansi_for(GRAPHITE.s_warn)
    model_chunk = line.split("|")[2]
    assert ink in model_chunk
    assert s_hot not in model_chunk
    assert s_warn not in model_chunk


def test_ctx_pct_zero_renders_calm():
    """Genuine 0% context (early in session) is calm s_ok, not None."""
    line = format_status_line(
        msgs_pct=10, tkns_pct=None, reset_time="2h00m",
        weekly_pct=10, reset_time_7d="3d00h",
        model="Opus 4.7(0/1M)", ctx_pct=0.0,
        theme=GRAPHITE, use_color=True,
    )
    s_ok = _ansi_for(GRAPHITE.s_ok)
    assert s_ok in line.split("|")[2]


def test_theme_switch_changes_classic_palette():
    """Same input rendered under graphite vs linen produces different ANSI.
    This is the regression test that proves classic actually respects themes."""
    args = dict(
        msgs_pct=10, tkns_pct=None, reset_time="2h00m",
        weekly_pct=10, reset_time_7d="3d00h",
        model="Opus 4.7", ctx_pct=None, use_color=True,
    )
    line_g = format_status_line(theme=get_theme("graphite"), **args)
    line_l = format_status_line(theme=get_theme("linen"), **args)
    assert line_g != line_l
    assert _ansi_for(get_theme("graphite").s_ok) in line_g
    assert _ansi_for(get_theme("linen").s_ok) in line_l


def test_use_color_false_strips_ansi():
    """All severity combinations produce ANSI-free output when use_color=False."""
    line = format_status_line(
        msgs_pct=80, tkns_pct=None, reset_time="2h00m",
        weekly_pct=80, reset_time_7d="3d00h",
        model="Opus 4.7(900k/1M)", ctx_pct=85,
        theme=GRAPHITE, use_color=False,
    )
    assert ANSI_RE.search(line) is None


def test_brackets_use_theme_mute():
    """[ and ] around the battery bar are colored theme.mute, not severity."""
    line = format_status_line(
        msgs_pct=80, tkns_pct=None, reset_time="2h00m",
        weekly_pct=10, reset_time_7d="3d00h",
        model="Opus 4.7", ctx_pct=None,
        theme=GRAPHITE, use_color=True,
    )
    mute = _ansi_for(GRAPHITE.mute)
    assert f"{mute}[" in line
    assert f"{mute}]" in line


def test_parens_around_context_use_theme_mute():
    """( and ) wrapping (used/size) are theme.mute; the numbers inside stay severity."""
    line = format_status_line(
        msgs_pct=10, tkns_pct=None, reset_time="2h00m",
        weekly_pct=10, reset_time_7d="3d00h",
        model="Opus 4.7(280k/1M)", ctx_pct=20,
        theme=GRAPHITE, use_color=True,
    )
    mute = _ansi_for(GRAPHITE.mute)
    assert f"{mute}(" in line
    assert f"{mute})" in line


def test_paren_muting_targets_the_last_bracket_not_the_first():
    """Model names that already contain parens (e.g. version annotations)
    must not have THOSE muted — only the trailing (used/size) bracket.
    Regression test for a regex anchor bug."""
    line = format_status_line(
        msgs_pct=10, tkns_pct=None, reset_time="2h00m",
        weekly_pct=10, reset_time_7d="3d00h",
        model="Opus(beta) 4.7(280k/1M)", ctx_pct=20,
        theme=GRAPHITE, use_color=True,
    )
    mute = _ansi_for(GRAPHITE.mute)
    s_ok = _ansi_for(GRAPHITE.s_ok)
    # Tighter regression: the version annotation `(beta)` must be inside the
    # severity-colored block (no mute prefix on it), and exactly ONE paren in
    # the whole line should be muted (the trailing context bracket).
    assert f"{s_ok}Opus(beta) 4.7" in line, "version paren must stay severity-colored"
    assert line.count(f"{mute}(") == 1, "exactly one '(' should carry mute"
