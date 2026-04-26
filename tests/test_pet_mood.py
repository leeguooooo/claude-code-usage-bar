"""Pet mood ladder must follow user-configured thresholds.

Regression: until v2.8.13 the mood transitions were hardcoded at 20/50/70%,
which silently desynced from the bar's color ladder when users customized
--warning-threshold or --critical-threshold. The pet face/text could read
"panic!!" while the bar was still calm green.
"""

import pytest

from claude_statusbar.pet import _get_mood, format_pet


def test_default_thresholds_match_bar_color_ladder():
    """With defaults (warn=30, crit=70), pet mood should match bar tier."""
    assert _get_mood(10, 12) == "chill"            # below warn*0.65 = 19.5
    assert _get_mood(25, 12) == "working"          # between warn*0.65 and warn
    assert _get_mood(40, 12) == "nervous"          # between warn and critical
    assert _get_mood(75, 12) == "panic"            # above critical


def test_aggressive_critical_threshold():
    """User sets critical=50: pct=51 should be panic."""
    assert _get_mood(40, 12, critical_threshold=50) == "nervous"
    assert _get_mood(51, 12, critical_threshold=50) == "panic"


def test_lax_critical_threshold():
    """User sets critical=80: pct=72 should still be nervous, not panic."""
    assert _get_mood(72, 12, warning_threshold=30, critical_threshold=80) == "nervous"
    assert _get_mood(81, 12, warning_threshold=30, critical_threshold=80) == "panic"


def test_warning_threshold_shifts_chill_working_boundary():
    """Higher warning threshold pushes the chill→working boundary up."""
    # warn=50: chill ≤ 32.5, working between 32.5 and 50
    assert _get_mood(30, 12, warning_threshold=50, critical_threshold=70) == "chill"
    assert _get_mood(40, 12, warning_threshold=50, critical_threshold=70) == "working"


def test_format_pet_passes_thresholds_through(tmp_path):
    """format_pet must thread thresholds into _get_mood — not silently use
    the hardcoded defaults."""
    # Pin time-dependent state so we can compare deterministically.
    out_panic = format_pet(72, 12, session_id="x",
                            warning_threshold=30, critical_threshold=70)
    out_nervous = format_pet(72, 12, session_id="x",
                              warning_threshold=30, critical_threshold=80)
    # Status text pools differ between panic / nervous moods, so the strings
    # must differ (face glyphs are similar but the suffix differs).
    assert "panic" in _mood_of(out_panic) or "!!" in out_panic
    assert "panic" not in _mood_of(out_nervous), \
        f"expected non-panic mood with critical=80 at pct=72, got {out_nervous!r}"


def _mood_of(s: str) -> str:
    """Heuristic: panic statuses end in `!!`."""
    return "panic" if s.endswith("!!") else "other"
