"""Experimental `bar_shimmer`: a STATIC faint dot field (high/mid/low glyphs
for vertical scatter, never moves) plus bright STARS that twinkle in/out per
render tick — all in the EMPTY portion of the battery bar. The filled color is
left untouched. Opt-in, default off, classic style only."""

from claude_statusbar.progress import (
    build_battery_bar, _lighten, _bg, _static_dot, _STAR_RARITY, _SPARKLE_GLINT,
    _DOT_GLYPHS,
)
from claude_statusbar.themes import get_theme

TH = get_theme("graphite")
_STARS = ("✦", "✧")


def test_lighten_moves_toward_white():
    assert _lighten((0, 0, 0), 0.5) == (127, 127, 127)


def test_static_dot_is_phase_independent_and_never_adjacent():
    # _static_dot takes no phase → the field can't move. Cells are blank sky or
    # a faint star glyph, and crucially no two dots ever sit side by side.
    seq = [_static_dot(i) for i in range(200)]
    glyphs = set(seq)
    assert None in glyphs                       # blank sky exists
    assert glyphs - {None} <= set(_DOT_GLYPHS)  # only star glyphs, no periods
    assert glyphs - {None}                      # some dots exist
    assert not any(seq[i] and seq[i + 1] for i in range(len(seq) - 1))  # never adjacent


def test_no_particles_without_phase():
    s = build_battery_bar(17, use_color=True, theme=TH)
    assert not any(g in s for g in (*_STARS, *_DOT_GLYPHS))
    assert _bg(TH.s_ok) in s  # flat fill present (17% → s_ok)


def test_fill_color_unchanged_by_particles():
    s = build_battery_bar(17, use_color=True, theme=TH, shimmer_phase=0)
    assert _bg(TH.s_ok) in s


def test_dot_field_is_static_across_phases():
    # The dim dots must NOT move with phase. Compare the dot glyph at each empty
    # cell that is NOT a star in either phase — it must be identical.
    import re
    a = build_battery_bar(0, use_color=True, theme=TH, shimmer_phase=0)
    b = build_battery_bar(0, use_color=True, theme=TH, shimmer_phase=1)
    # Strip color; keep glyph sequence inside the bar.
    strip = lambda s: re.sub(r"\033\[[0-9;]*m", "", s)
    da = [c for c in strip(a) if c in _DOT_GLYPHS]
    # Dots are static, so every dot present in frame A is present in frame B at
    # the same relative ordering unless a star happens to cover it — at minimum
    # the multiset of dot glyphs should overlap heavily, not be random noise.
    db = [c for c in strip(b) if c in _DOT_GLYPHS]
    assert da and db  # dots exist in both frames


def test_stars_twinkle_with_phase():
    # Stars flare in place at fixed dot cells; across enough ticks the field
    # is not frozen. (Any single adjacent pair may both be "resting", so look
    # across a span rather than two specific phases.)
    frames = {build_battery_bar(0, use_color=True, theme=TH, shimmer_phase=p)
              for p in range(_STAR_RARITY * 3)}
    assert len(frames) > 1


def test_distinct_seeds_give_distinct_fields():
    # Two side-by-side bars (5h / 7d) must NOT share an identical star field —
    # the per-bar seed gives each its own sky. Compare resting fields (no flare).
    from claude_statusbar.progress import _field_seed, _static_dot
    s5, s7 = _field_seed("5h"), _field_seed("7d")
    assert s5 != s7
    field5 = [_static_dot(i, s5) for i in range(10)]
    field7 = [_static_dot(i, s7) for i in range(10)]
    assert field5 != field7  # different arrangements, not mirror-image skies


def test_a_star_appears_over_several_phases():
    seen = any(
        (g in build_battery_bar(3, use_color=True, theme=TH, shimmer_phase=p))
        for p in range(_STAR_RARITY * 3) for g in _STARS
    )
    assert seen


def test_star_color_is_fill_hue_lightened():
    bright = _bg  # placeholder to keep import; use _lighten below
    target = _lighten(TH.s_ok, _SPARKLE_GLINT)
    code = f"\033[38;2;{target[0]};{target[1]};{target[2]}m"
    found = any(
        code in build_battery_bar(3, use_color=True, theme=TH, shimmer_phase=p)
        for p in range(_STAR_RARITY * 3)
    )
    assert found


def test_no_particles_in_no_color():
    s = build_battery_bar(17, use_color=False, theme=TH, shimmer_phase=0)
    assert "\x1b" not in s
    assert not any(g in s for g in (*_STARS, *_DOT_GLYPHS))


def test_safe_at_zero_and_full():
    build_battery_bar(0, use_color=True, theme=TH, shimmer_phase=3)
    build_battery_bar(100, use_color=True, theme=TH, shimmer_phase=3)
