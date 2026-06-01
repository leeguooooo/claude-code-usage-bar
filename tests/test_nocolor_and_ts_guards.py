"""Regression guards for two pre-existing defensive gaps fixed alongside the
live-activity feature:
  1. render_classic leaked a raw RESET (`\\x1b[0m`) into the cache segment
     even when use_color=False — non-color consumers saw a literal `[0m`.
  2. core._entry_age crashed (AttributeError) on a non-string timestamp.
"""

from claude_statusbar.core import _entry_age
from claude_statusbar.styles import render
from claude_statusbar.themes import get_theme

THEME = get_theme("graphite")


def test_classic_cache_segment_no_ansi_when_color_off():
    out = render("classic", msgs_pct=10, weekly_pct=20, model="Opus 4.8",
                 reset_5h="1h", reset_7d="6d", cache_age_text="3m24s",
                 use_color=False, theme=THEME)
    assert "\x1b" not in out
    assert "[0m" not in out
    assert "cache 3m24s" in out


def test_classic_cache_cold_no_ansi_when_color_off():
    out = render("classic", msgs_pct=10, weekly_pct=20, model="Opus 4.8",
                 reset_5h="1h", reset_7d="6d", cache_age_text="COLD",
                 use_color=False, theme=THEME)
    assert "\x1b" not in out
    assert "[0m" not in out


def test_entry_age_non_string_timestamp_returns_none():
    assert _entry_age({"timestamp": 1234567890}) is None
    assert _entry_age({"timestamp": ["2026"]}) is None


def test_entry_age_missing_timestamp_returns_none():
    assert _entry_age({}) is None
