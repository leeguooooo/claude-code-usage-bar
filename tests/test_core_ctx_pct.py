"""Unit tests for the ctx_pct nullable-discriminator logic in core.py.

The discriminator runs against a flattened stdin_data dict produced by
core.py:568-575 (which reads `data['context_window']['used_percentage']`
and writes it as top-level `context_used_pct`). These tests feed the
already-flattened shape directly.
"""

from claude_statusbar import core


def _compute_ctx_pct(stdin_data):
    return core._context_window_usage(stdin_data)[0]


def test_no_context_window_yields_none():
    """Missing context_window_size means context segment is not surfaced."""
    assert _compute_ctx_pct({}) is None
    assert _compute_ctx_pct({"context_used_pct": 50}) is None  # size=0
    assert _compute_ctx_pct({"context_window_size": 0, "context_used_pct": 50}) is None


def test_zero_pct_context_renders_calm():
    """Genuine 0% (early in session) returns 0.0, not None.
    This is the falsy-0 trap from spec review."""
    out = _compute_ctx_pct({"context_window_size": 1_000_000, "context_used_pct": 0})
    assert out == 0.0
    assert out is not None


def test_normal_context_returns_float():
    out = _compute_ctx_pct({"context_window_size": 1_000_000, "context_used_pct": 42})
    assert out == 42.0
    assert isinstance(out, float)


def test_used_tokens_come_from_exact_totals_not_rounded_pct():
    """used_percentage is a whole number; on a 1M window that quantises the
    token readout to 10k steps. The exact totals must win."""
    ctx_pct, _, ctx_used = core._context_window_usage({
        "context_window_size": 1_000_000,
        "context_used_pct": 6,
        "total_input_tokens": 63_824,
        "total_output_tokens": 0,
    })
    assert ctx_used == 63_824  # not 60_000
    assert ctx_pct == 6.0      # percentage stays as Claude Code reported it


def test_used_tokens_fall_back_to_pct_when_totals_absent():
    """Older Claude Code / relay payloads omit the totals entirely."""
    _, _, ctx_used = core._context_window_usage({
        "context_window_size": 200_000,
        "context_used_pct": 25,
    })
    assert ctx_used == 50_000


def test_malformed_totals_fall_back_to_pct():
    _, _, ctx_used = core._context_window_usage({
        "context_window_size": 200_000,
        "context_used_pct": 25,
        "total_input_tokens": "lots",
    })
    assert ctx_used == 50_000


def test_null_context_pct_is_unknown_not_error():
    ctx_pct, ctx_size, ctx_used = core._context_window_usage({
        "context_window_size": 1_000_000,
        "context_used_pct": None,
        "total_input_tokens": 1200,
        "total_output_tokens": 34,
    })
    assert ctx_pct is None
    assert ctx_size == 1_000_000
    assert ctx_used == 1234
