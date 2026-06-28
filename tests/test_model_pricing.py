"""Model-aware token pricing.

Regression coverage for the v4.0.0-inspired fix: every model used to be priced
at flat Sonnet-3.5 rates ($3/$15), which over-charged Opus 4.5+ (legacy $15/$75)
and silently billed non-Anthropic relay/router models as Claude. Pricing is now
keyed off the model string, and non-Claude / synthetic models report $0.
"""

import pytest

from claude_statusbar.core import model_pricing


@pytest.mark.parametrize(
    "model,expected",
    [
        # Opus 4.5+ uses the new low rate …
        ("claude-opus-4-8", (5.0, 25.0)),
        ("claude-opus-4-5-20251101", (5.0, 25.0)),
        ("claude-opus-4-6", (5.0, 25.0)),
        # … while 3 / 4.0 / 4.1 keep the legacy rate.
        ("claude-opus-4-1-20250805", (15.0, 75.0)),
        ("claude-opus-4-20250514", (15.0, 75.0)),
        ("claude-3-opus-20240229", (15.0, 75.0)),
        # Sonnet family (≤200k standard tier).
        ("claude-sonnet-4-6", (3.0, 15.0)),
        ("claude-sonnet-4-5-20250929", (3.0, 15.0)),
        ("claude-3-5-sonnet-20241022", (3.0, 15.0)),
        # Haiku tiers.
        ("claude-haiku-4-5-20251001", (1.0, 5.0)),
        ("claude-3-5-haiku-20241022", (0.8, 4.0)),
        ("claude-3-haiku-20240307", (0.25, 1.25)),
        # Fable.
        ("claude-fable-5", (10.0, 50.0)),
    ],
)
def test_claude_models_priced(model, expected):
    assert model_pricing(model) == expected


@pytest.mark.parametrize(
    "model",
    [
        "gpt-4o",
        "gpt-5",
        "deepseek-chat",
        "deepseek-r1",
        "gemini-2.0-flash",
        "qwen2.5-coder",
        "<synthetic>",
        "",
        None,
    ],
)
def test_non_claude_and_synthetic_unpriced(model):
    """Relay/router non-Anthropic models and synthetic messages cost $0 — never
    billed at a fabricated Claude rate."""
    assert model_pricing(model) == (0.0, 0.0)


def test_unknown_claude_falls_back_to_sonnet():
    assert model_pricing("claude-something-future") == (3.0, 15.0)
