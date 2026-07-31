"""Context-window usage parsing and occupancy semantics."""

import io
import json
import sys

import pytest

from claude_statusbar import core


def _compute_ctx_pct(stdin_data):
    return core._context_window_usage(stdin_data)[0]


def _parse(monkeypatch, payload):
    fake = io.StringIO(json.dumps(payload))
    fake.isatty = lambda: False
    monkeypatch.setattr(sys, "stdin", fake)
    return core.parse_stdin_data()


def test_no_context_window_yields_none():
    """Missing context_window_size means context segment is not surfaced."""
    assert _compute_ctx_pct({}) is None
    assert _compute_ctx_pct({"context_used_pct": 50}) is None
    assert _compute_ctx_pct({
        "context_window_size": 0,
        "context_used_pct": 50,
    }) is None


def test_zero_pct_context_renders_calm():
    """Genuine 0% (early in session) returns 0.0, not None."""
    out = _compute_ctx_pct({
        "context_window_size": 1_000_000,
        "context_used_pct": 0,
    })
    assert out == 0.0
    assert out is not None


def test_normal_context_returns_float():
    out = _compute_ctx_pct({
        "context_window_size": 1_000_000,
        "context_used_pct": 42,
    })
    assert out == 42.0
    assert isinstance(out, float)


def test_parse_preserves_current_usage_and_version(monkeypatch):
    current = {
        "input_tokens": 40_000,
        "cache_creation_input_tokens": 3_824,
        "cache_read_input_tokens": 20_000,
        "output_tokens": 9_999,
    }
    parsed = _parse(monkeypatch, {
        "version": "2.1.220",
        "context_window": {
            "context_window_size": 1_000_000,
            "used_percentage": 6,
            "total_input_tokens": 999_999,
            "total_output_tokens": 888_888,
            "current_usage": current,
        },
    })

    assert parsed["context_current_usage"] == current
    assert parsed["claude_version"] == "2.1.220"


def test_parse_preserves_current_usage_absent_vs_null(monkeypatch):
    absent = _parse(monkeypatch, {
        "context_window": {"context_window_size": 200_000},
    })
    explicit_null = _parse(monkeypatch, {
        "context_window": {
            "context_window_size": 200_000,
            "current_usage": None,
        },
    })

    assert "context_current_usage" not in absent
    assert "context_current_usage" in explicit_null
    assert explicit_null["context_current_usage"] is None


def test_current_usage_input_and_cache_tokens_are_authoritative():
    ctx_pct, _, ctx_used = core._context_window_usage({
        "claude_version": "2.1.220",
        "context_window_size": 1_000_000,
        "context_used_pct": 6,
        "total_input_tokens": 999_999,
        "total_output_tokens": 888_888,
        "context_current_usage": {
            "input_tokens": 40_000,
            "cache_creation_input_tokens": 3_824,
            "cache_read_input_tokens": 20_000,
            "output_tokens": 9_999,
        },
    })

    assert ctx_used == 63_824
    assert ctx_pct == 6.0


def test_current_usage_can_report_exact_zero():
    _, _, ctx_used = core._context_window_usage({
        "context_window_size": 200_000,
        "context_used_pct": 7,
        "context_current_usage": {
            "input_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        },
    })
    assert ctx_used == 0


@pytest.mark.parametrize("version", ["2.1.131", "2.1.220", "", "junk"])
def test_totals_disagreeing_with_pct_fall_back_to_pct(version):
    """Cumulative-style totals are rejected on every version — the pct
    cross-check, not a version gate, decides whether totals are trusted."""
    _, _, ctx_used = core._context_window_usage({
        "claude_version": version,
        "context_window_size": 1_000_000,
        "context_used_pct": 6,
        "total_input_tokens": 1_500_000,
        "total_output_tokens": 900_000,
    })
    assert ctx_used == 60_000


def test_cumulative_session_totals_rejected_by_cross_check():
    """Real repro (2026-07-31): resume tick on 2.1.220 sent the cumulative
    session counter as total_input_tokens. 73.6M vs a 7% reading must render
    as the pct-derived 70k, not as '73.6M/1.0M'."""
    _, _, ctx_used = core._context_window_usage({
        "claude_version": "2.1.220",
        "context_window_size": 1_000_000,
        "context_used_pct": 7,
        "total_input_tokens": 73_623_000,
        "total_output_tokens": 296,
    })
    assert ctx_used == 70_000


def test_totals_consistent_with_pct_are_trusted_exactly():
    """Within quantization tolerance of used_percentage, the exact totals
    beat the 1%-quantized derivation. output tokens never count."""
    _, _, ctx_used = core._context_window_usage({
        "claude_version": "2.1.132",
        "context_window_size": 1_000_000,
        "context_used_pct": 6,
        "total_input_tokens": 63_824,
        "total_output_tokens": 999_999,
    })
    assert ctx_used == 63_824


@pytest.mark.parametrize("version", ["", "junk", "2.1.1"])
def test_current_usage_wins_without_reliable_version(version):
    _, _, ctx_used = core._context_window_usage({
        "claude_version": version,
        "context_window_size": 200_000,
        "context_used_pct": 50,
        "total_input_tokens": 190_000,
        "context_current_usage": {
            "input_tokens": 1_000,
            "cache_creation_input_tokens": 200,
            "cache_read_input_tokens": 300,
            "output_tokens": 50_000,
        },
    })
    assert ctx_used == 1_500


@pytest.mark.parametrize("bad", [
    {"input_tokens": "lots"},
    {"input_tokens": -1},
    {"input_tokens": True},
    {"cache_read_input_tokens": 1.5},
])
def test_malformed_current_usage_falls_back_to_pct(bad):
    _, _, ctx_used = core._context_window_usage({
        "claude_version": "2.1.220",
        "context_window_size": 200_000,
        "context_used_pct": 25,
        "total_input_tokens": 190_000,
        "context_current_usage": bad,
    })
    assert ctx_used == 50_000


def test_explicit_null_current_usage_falls_back_to_pct_after_compact():
    _, _, ctx_used = core._context_window_usage({
        "claude_version": "2.1.220",
        "context_window_size": 1_000_000,
        "context_used_pct": 12,
        "total_input_tokens": 900_000,
        "context_current_usage": None,
    })
    assert ctx_used == 120_000


def test_used_tokens_fall_back_to_pct_when_totals_absent():
    _, _, ctx_used = core._context_window_usage({
        "context_window_size": 200_000,
        "context_used_pct": 25,
    })
    assert ctx_used == 50_000


def test_malformed_total_falls_back_to_pct():
    _, _, ctx_used = core._context_window_usage({
        "claude_version": "2.1.220",
        "context_window_size": 200_000,
        "context_used_pct": 25,
        "total_input_tokens": "lots",
    })
    assert ctx_used == 50_000


def test_first_tick_everything_null_reports_unknown_not_zero():
    """Session start/resume: null pct, null current_usage sentinel, totals
    zeroed or cumulative — no trustworthy signal at all. ctx_used must be
    None (renders as a bare model name), never a fabricated 0 or the
    cumulative counter."""
    ctx_pct, ctx_size, ctx_used = core._context_window_usage({
        "claude_version": "2.1.220",
        "context_window_size": 1_000_000,
        "context_used_pct": None,
        "context_current_usage": None,
        "total_input_tokens": 73_623_000,
    })
    assert ctx_pct is None
    assert ctx_size == 1_000_000
    assert ctx_used is None


def test_over_window_current_usage_is_kept_verbatim():
    """current_usage may honestly exceed the window while a compact is
    pending (seen live: 212k on a 200k window at 100%). Authoritative data
    is not clamped."""
    _, _, ctx_used = core._context_window_usage({
        "claude_version": "2.1.220",
        "context_window_size": 200_000,
        "context_used_pct": 100,
        "context_current_usage": {
            "input_tokens": 2,
            "cache_creation_input_tokens": 955,
            "cache_read_input_tokens": 211_129,
        },
    })
    assert ctx_used == 212_086


def test_null_context_pct_is_unknown_not_error():
    ctx_pct, ctx_size, ctx_used = core._context_window_usage({
        "context_window_size": 1_000_000,
        "context_used_pct": None,
        "context_current_usage": {
            "input_tokens": 1_000,
            "cache_creation_input_tokens": 100,
            "cache_read_input_tokens": 100,
            "output_tokens": 99_999,
        },
    })
    assert ctx_pct is None
    assert ctx_size == 1_000_000
    assert ctx_used == 1_200
