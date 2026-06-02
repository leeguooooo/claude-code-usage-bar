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
