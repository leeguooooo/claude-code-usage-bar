from claude_statusbar.progress import build_bar

def test_bar_zero_percent():
    assert build_bar(0, 10) == "░░░░░░░░░░"

def test_bar_fifty_percent():
    assert build_bar(50, 10) == "█████░░░░░"

def test_bar_100_percent():
    assert build_bar(100, 10) == "██████████"

def test_bar_over_100():
    assert build_bar(120, 10) == "██████████"

def test_bar_small_nonzero_rounds_up():
    """1% should show at least 1 filled block."""
    assert build_bar(1, 10) == "█░░░░░░░░░"

def test_bar_25_percent():
    """25% -> int(2.5 + 0.5) = 3 blocks (always rounds half-up, not banker's)."""
    assert build_bar(25, 10) == "███░░░░░░░"

def test_bar_15_percent():
    """15% -> int(1.5 + 0.5) = 2 blocks."""
    assert build_bar(15, 10) == "██░░░░░░░░"

def test_bar_boundary_values():
    """Test at various boundaries to confirm half-up rounding."""
    assert build_bar(5, 10) == "█░░░░░░░░░"   # int(0.5+0.5)=1
    assert build_bar(45, 10) == "█████░░░░░"   # int(4.5+0.5)=5
    assert build_bar(99, 10) == "██████████"    # int(9.9+0.5)=10

from claude_statusbar.progress import (
    color_for_percent,
    colorize,
    normalize_thresholds,
    GREEN,
    YELLOW,
    RED,
    RESET,
)

def test_color_safe():
    assert color_for_percent(20) == GREEN

def test_color_warning():
    assert color_for_percent(50) == YELLOW

def test_color_critical():
    assert color_for_percent(80) == RED

def test_color_boundary_30():
    assert color_for_percent(30) == YELLOW

def test_color_boundary_70():
    assert color_for_percent(70) == RED

def test_color_custom_thresholds():
    assert color_for_percent(39, warning_threshold=40, critical_threshold=80) == GREEN
    assert color_for_percent(40, warning_threshold=40, critical_threshold=80) == YELLOW
    assert color_for_percent(80, warning_threshold=40, critical_threshold=80) == RED

def test_normalize_thresholds_rejects_invalid_ranges():
    try:
        normalize_thresholds(80, 40)
    except ValueError as exc:
        assert "warning < critical" in str(exc)
    else:
        raise AssertionError("Expected invalid thresholds to raise ValueError")

def test_colorize():
    result = colorize("hello", RED)
    assert result == f"{RED}hello{RESET}"

def test_colorize_no_color():
    result = colorize("hello", RED, use_color=False)
    assert result == "hello"

from claude_statusbar.progress import format_status_line

def test_format_status_line_basic():
    line = format_status_line(
        msgs_pct=82, tkns_pct=None,
        reset_time="2h51m", model="Opus 4.6",
        weekly_pct=45,
        use_color=False,
    )
    assert "5h[" in line
    assert "7d[" in line
    assert "2h51m" in line
    assert "Opus 4.6" in line

def test_format_status_line_over_100():
    line = format_status_line(
        msgs_pct=105, tkns_pct=None,
        reset_time="0h03m", model="Opus 4.6",
        weekly_pct=100,
        use_color=False,
    )
    assert "5h[" in line
    assert "MAX" in line

def test_format_status_line_no_data():
    line = format_status_line(
        msgs_pct=None, tkns_pct=None,
        reset_time="--", model="unknown",
        weekly_pct=None,
        use_color=False,
    )
    assert "5h[" in line
    assert "7d[" in line
    assert "--%" in line

def test_format_status_line_bypass():
    line = format_status_line(
        msgs_pct=50, tkns_pct=None,
        reset_time="3h00m", model="Sonnet",
        weekly_pct=20,
        bypass=True, use_color=False,
    )
    assert "BYPASS" in line

def test_format_status_line_7d_countdown():
    """7d countdown should appear next to the 7d progress bar."""
    line = format_status_line(
        msgs_pct=50, tkns_pct=None,
        reset_time="2h30m", model="Opus 4.6",
        weekly_pct=30, reset_time_7d="3d05h",
        use_color=False,
    )
    assert "7d[" in line
    assert "3d05h" in line
    assert "2h30m" in line

def test_format_status_line_7d_no_countdown():
    """When reset_time_7d is empty, no extra countdown after 7d bar."""
    line = format_status_line(
        msgs_pct=50, tkns_pct=None,
        reset_time="2h30m", model="Opus 4.6",
        weekly_pct=30, reset_time_7d="",
        use_color=False,
    )
    assert "7d[" in line
    # 5h has ⏰, 7d does not (no reset_time_7d)
    assert "⏰2h30m" in line

def test_format_status_line_with_color():
    """Verify ANSI codes are present when use_color=True."""
    line = format_status_line(
        msgs_pct=80, tkns_pct=None,
        reset_time="1h00m", model="Opus",
        weekly_pct=30,
        use_color=True,
    )
    assert "\033[" in line
    assert "\033[0m" in line


# ── language segment tests ────────────────────────────────────────────────────

import json
import os
import pytest
from claude_statusbar import progress as _prog
from claude_statusbar.progress import format_language_segment


@pytest.fixture(autouse=True)
def _enable_coach(monkeypatch):
    """The language segment is gated on language-coach being enabled.
    These tests are about the formatting, so unconditionally enable it."""
    monkeypatch.setattr(_prog, "_coach_enabled", lambda *a, **kw: True)


def test_format_language_segment_missing_file():
    assert format_language_segment("/nonexistent/path.json", use_color=False) == ""

def test_format_language_segment_invalid_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("not json", encoding="utf-8")
    assert format_language_segment(str(p), use_color=False) == ""

def test_format_language_segment_basic(tmp_path):
    data = {
        "English": {
            "estimates": [
                {"date": "2026-04-14", "band": "5.5"},
                {"date": "2026-04-15", "band": "6.0"},
            ],
            "currentBand": "6.0",
        }
    }
    p = tmp_path / "progress.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    result = format_language_segment(str(p), use_color=False)
    assert result == "📚 EN:6.0↑"

def test_format_language_segment_japanese(tmp_path):
    data = {
        "Japanese": {
            "estimates": [{"date": "2026-04-15", "band": "5.0"}],
            "currentBand": "5.0",
        }
    }
    p = tmp_path / "progress.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    result = format_language_segment(str(p), use_color=False)
    assert result == "📚 JA:5.0→"

def test_format_language_segment_multiple(tmp_path):
    data = {
        "English": {
            "estimates": [
                {"date": "2026-04-14", "band": "5.5"},
                {"date": "2026-04-15", "band": "5.0"},
            ],
            "currentBand": "5.0",
        },
        "Japanese": {
            "estimates": [{"date": "2026-04-15", "band": "5.0"}],
            "currentBand": "5.0",
        },
    }
    p = tmp_path / "progress.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    result = format_language_segment(str(p), use_color=False)
    assert "EN:5.0↓" in result
    assert "JA:5.0→" in result
    assert result.startswith("📚 ")

def test_format_status_line_with_lang_text():
    line = format_status_line(
        msgs_pct=50, tkns_pct=None,
        reset_time="2h00m", model="Opus 4.6",
        weekly_pct=30,
        use_color=False,
        lang_text="📚 EN:6.0↑",
        pet_text="ᓚᘏᗢ",
    )
    assert "📚 EN:6.0↑" in line
    # lang_text appears between model and pet
    model_pos = line.index("Opus 4.6")
    lang_pos = line.index("📚")
    pet_pos = line.index("ᓚᘏᗢ")
    assert model_pos < lang_pos < pet_pos


def test_language_segment_capped_at_max_languages(monkeypatch, tmp_path):
    """A bloated language-progress.json must not let the segment expand
    indefinitely and push the rest of the status line off-screen."""
    monkeypatch.setattr(_prog, "_coach_enabled", lambda *a, **kw: True)
    payload = {f"Lang{i:03d}": {"currentBand": "5.0"} for i in range(50)}
    p = tmp_path / "progress.json"
    p.write_text(json.dumps(payload), encoding="utf-8")

    out = _prog.format_language_body(str(p))
    # Each entry is "XX:5.0→" = 7 chars + 1 space ⇒ N entries = 7N + (N-1) chars
    # Cap is MAX_LANGUAGES; output length ≤ 8 * cap to give a comfortable upper bound.
    parts = out.split(" ")
    assert len(parts) == _prog.MAX_LANGUAGES, (
        f"expected {_prog.MAX_LANGUAGES} entries, got {len(parts)}: {out!r}"
    )


def test_language_logging_does_not_clobber_root(monkeypatch):
    """Importing claude_statusbar must not call logging.basicConfig() —
    that would override host applications' logging config."""
    import importlib
    import logging as _logging

    # Capture the root logger handlers BEFORE re-importing.
    root = _logging.getLogger()
    handlers_before = list(root.handlers)
    level_before = root.level

    import claude_statusbar.core
    importlib.reload(claude_statusbar.core)

    handlers_after = list(root.handlers)
    level_after = root.level
    assert handlers_after == handlers_before, "core.py polluted root logger handlers"
    assert level_after == level_before, "core.py reset root logger level"
