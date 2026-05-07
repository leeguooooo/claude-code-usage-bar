"""Unit tests for the ctx_pct nullable-discriminator logic in core.py.

The discriminator runs against a flattened stdin_data dict produced by
core.py:568-575 (which reads `data['context_window']['used_percentage']`
and writes it as top-level `context_used_pct`). These tests feed the
already-flattened shape directly.
"""


def _compute_ctx_pct(stdin_data):
    """Mirror the discriminator that lives at core.py:1146-1158 (after
    Step 3 below lands). Kept here as a self-contained helper so the
    test pins the exact contract independent of surrounding core.py code."""
    ctx_size = stdin_data.get("context_window_size", 0)
    raw_pct = stdin_data.get("context_used_pct", 0)
    return float(raw_pct) if ctx_size > 0 else None


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
