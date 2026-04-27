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
            "five_hour": {"used_percentage": -5, "resets_at": 9999999999},
            "seven_day": {"used_percentage": -1, "resets_at": 9999999999},
        },
    }, monkeypatch)
    out = core.parse_stdin_data()
    assert out["rate_limit_pct"] == 0
    assert out["rate_limit_7d_pct"] == 0


def test_pct_rejects_nan(monkeypatch, isolated_cache):
    _stdin_with({
        "rate_limits": {
            "five_hour": {"used_percentage": float("nan"), "resets_at": 9999999999},
        },
    }, monkeypatch)
    out = core.parse_stdin_data()
    assert out["rate_limit_pct"] == 0


def test_pct_rejects_inf(monkeypatch, isolated_cache):
    _stdin_with({
        "rate_limits": {
            "five_hour": {"used_percentage": float("inf"), "resets_at": 9999999999},
        },
    }, monkeypatch)
    out = core.parse_stdin_data()
    assert out["rate_limit_pct"] == 0


def test_pct_preserves_over_100(monkeypatch, isolated_cache):
    """Values >100 are legitimate (over-quota indicator) and must NOT be capped."""
    _stdin_with({
        "rate_limits": {
            "five_hour": {"used_percentage": 110, "resets_at": 9999999999},
        },
    }, monkeypatch)
    out = core.parse_stdin_data()
    assert out["rate_limit_pct"] == 110


def test_pct_rounds_floating_point_drift(monkeypatch, isolated_cache):
    """Anthropic occasionally returns 56.00000000000001."""
    _stdin_with({
        "rate_limits": {
            "five_hour": {"used_percentage": 56.00000000000001, "resets_at": 9999999999},
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


# ---------------------------------------------------------------------------
# Time-based window rollover.
# Anthropic only pushes fresh rate_limits when a request actually fires.
# Between requests, the value we have can describe an already-expired
# window. Showing "99%" hours after the reset is misleading; once
# resets_at < now() we MUST roll over to 0% in the new window.
# ---------------------------------------------------------------------------
import time as _time


def test_5h_window_rollover_when_resets_at_in_past(monkeypatch, isolated_cache):
    """Anthropic sent 99% with resets_at = 1h ago. We must show 0%, with
    resets_at advanced into the future."""
    now = _time.time()
    expired_resets_at = int(now - 3600)  # 1 hour ago
    _stdin_with({
        "rate_limits": {
            "five_hour": {"used_percentage": 99, "resets_at": expired_resets_at},
        },
    }, monkeypatch)
    out = core.parse_stdin_data()
    assert out["rate_limit_pct"] == 0, "stale 99% leaked into a new window"
    assert out["rate_limit_resets_at"] > now, "resets_at must be in the future"


def test_7d_window_rollover_when_resets_at_in_past(monkeypatch, isolated_cache):
    now = _time.time()
    expired = int(now - 86400 * 2)  # 2 days ago
    _stdin_with({
        "rate_limits": {
            "seven_day": {"used_percentage": 88, "resets_at": expired},
        },
    }, monkeypatch)
    out = core.parse_stdin_data()
    assert out["rate_limit_7d_pct"] == 0
    assert out["rate_limit_7d_resets_at"] > now


def test_rollover_advances_through_multiple_expired_windows(monkeypatch, isolated_cache):
    """If user was offline for 2 weeks, the 7d window has rolled over twice.
    resets_at should land in the FUTURE, not 1 day ago."""
    now = _time.time()
    very_old = int(now - 86400 * 14)  # 14 days ago
    _stdin_with({
        "rate_limits": {
            "seven_day": {"used_percentage": 100, "resets_at": very_old},
        },
    }, monkeypatch)
    out = core.parse_stdin_data()
    assert out["rate_limit_7d_resets_at"] > now


def test_no_rollover_when_window_still_active(monkeypatch, isolated_cache):
    """resets_at in the future → leave pct alone."""
    now = _time.time()
    future = int(now + 3600)  # 1 hour from now
    _stdin_with({
        "rate_limits": {
            "five_hour": {"used_percentage": 47, "resets_at": future},
        },
    }, monkeypatch)
    out = core.parse_stdin_data()
    assert out["rate_limit_pct"] == 47
    assert out["rate_limit_resets_at"] == future


def test_cached_stdin_is_also_rolled_over(monkeypatch, isolated_cache, tmp_path):
    """When current stdin lacks rate_limits, we read from
    last_stdin.json. That cached value's resets_at can also be expired —
    rollover must apply there too."""
    # Pre-populate cache with stale data
    cache_dir = tmp_path / ".cache" / "claude-statusbar"
    cache_dir.mkdir(parents=True)
    expired = int(_time.time() - 3600)
    cache_dir.joinpath("last_stdin.json").write_text(json.dumps({
        "rate_limits": {
            "five_hour": {"used_percentage": 99, "resets_at": expired},
        },
    }), encoding="utf-8")

    # Current stdin has NO rate_limits
    _stdin_with({"session_id": "abc"}, monkeypatch)
    out = core.parse_stdin_data()
    assert out.get("rate_limit_pct") == 0, "rolled-over cache fallback failed"
