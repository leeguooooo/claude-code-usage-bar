"""Test parse_stdin_data percent clamping (regression)."""

import json
import os
import sys
from io import StringIO

import pytest

from claude_statusbar import core


def _stdin_with(payload: dict, monkeypatch):
    raw = json.dumps(payload)
    fake = StringIO(raw)
    fake.isatty = lambda: False
    monkeypatch.setattr(sys, "stdin", fake)


@pytest.fixture
def isolated_cache(monkeypatch, tmp_path):
    """Redirect ~/.cache so the test never touches the user's real cache."""
    monkeypatch.setattr(core.Path, "home", classmethod(lambda cls: tmp_path))
    return tmp_path


def test_pct_clamps_negative(monkeypatch, isolated_cache):
    _stdin_with({
        "rate_limits": {
            "five_hour": {"used_percentage": -5, "resets_at": 0},
            "seven_day": {"used_percentage": -1, "resets_at": 0},
        },
    }, monkeypatch)
    out = core.parse_stdin_data()
    assert out["rate_limit_pct"] == 0
    assert out["rate_limit_7d_pct"] == 0


def test_pct_rejects_nan(monkeypatch, isolated_cache):
    _stdin_with({
        "rate_limits": {
            "five_hour": {"used_percentage": float("nan"), "resets_at": 0},
        },
    }, monkeypatch)
    out = core.parse_stdin_data()
    assert out["rate_limit_pct"] == 0


def test_pct_rejects_inf(monkeypatch, isolated_cache):
    _stdin_with({
        "rate_limits": {
            "five_hour": {"used_percentage": float("inf"), "resets_at": 0},
        },
    }, monkeypatch)
    out = core.parse_stdin_data()
    assert out["rate_limit_pct"] == 0


def test_pct_preserves_over_100(monkeypatch, isolated_cache):
    """Values >100 are legitimate (over-quota indicator) and must NOT be capped."""
    _stdin_with({
        "rate_limits": {
            "five_hour": {"used_percentage": 110, "resets_at": 0},
        },
    }, monkeypatch)
    out = core.parse_stdin_data()
    assert out["rate_limit_pct"] == 110


def test_pct_rounds_floating_point_drift(monkeypatch, isolated_cache):
    """Anthropic occasionally returns 56.00000000000001."""
    _stdin_with({
        "rate_limits": {
            "five_hour": {"used_percentage": 56.00000000000001, "resets_at": 0},
        },
    }, monkeypatch)
    out = core.parse_stdin_data()
    assert out["rate_limit_pct"] == 56


# ---------------------------------------------------------------------------
# _has_stdin must be set as soon as JSON parses, NOT only after every field
# is successfully extracted. Otherwise an unexpected sub-field shape silently
# kicks main() into the "no stdin" path even though we have valid data.
# ---------------------------------------------------------------------------
def test_has_stdin_set_when_only_minimal_payload(monkeypatch, isolated_cache):
    _stdin_with({"session_id": "abc"}, monkeypatch)
    out = core.parse_stdin_data()
    assert out.get("_has_stdin") is True
    assert out.get("session_id") == "abc"


def test_has_stdin_survives_unexpected_subfield_shape(monkeypatch, isolated_cache):
    """Anthropic ships a list where we expect a dict — partial extraction
    must still mark stdin as valid. Regression: prior to v2.8.11 the
    AttributeError thrown by some `.get()` would skip the trailing
    `_has_stdin = True` line."""
    _stdin_with({
        "session_id": "abc",
        "rate_limits": "this should be a dict but isn't",
    }, monkeypatch)
    out = core.parse_stdin_data()
    assert out.get("_has_stdin") is True


def test_has_stdin_unset_on_invalid_json(monkeypatch, isolated_cache):
    fake = type("F", (), {})()
    fake.isatty = lambda: False
    fake.read = lambda: "{not valid json"
    monkeypatch.setattr(sys, "stdin", fake)

    out = core.parse_stdin_data()
    assert out.get("_has_stdin") is None


def test_has_stdin_unset_when_stdin_empty(monkeypatch, isolated_cache):
    fake = type("F", (), {})()
    fake.isatty = lambda: False
    fake.read = lambda: ""
    monkeypatch.setattr(sys, "stdin", fake)

    out = core.parse_stdin_data()
    assert out.get("_has_stdin") is None
