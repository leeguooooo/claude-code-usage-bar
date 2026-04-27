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
# Time-based window rollover (cached-fallback only).
# Fresh stdin from Anthropic is trusted verbatim — comparing its resets_at
# against the local clock can spuriously zero out a still-valid window on
# 1-second boundary, which made the statusbar flip between the real pct
# and 0% across renders.
# Rollover applies only to the cached fallback path, where it returns
# None (renders as "--", not authoritative 0%).
# ---------------------------------------------------------------------------
import time as _time


def test_fresh_stdin_pct_is_trusted_even_if_resets_at_just_passed(monkeypatch, isolated_cache):
    """Fresh stdin from Anthropic must NOT be mutated by a local clock
    comparison. resets_at sliding 1s past now() is a boundary artifact, not
    a window rollover."""
    now = _time.time()
    just_past = int(now - 1)
    _stdin_with({
        "rate_limits": {
            "five_hour": {"used_percentage": 47, "resets_at": just_past},
            "seven_day": {"used_percentage": 12, "resets_at": just_past},
        },
    }, monkeypatch)
    out = core.parse_stdin_data()
    assert out["rate_limit_pct"] == 47
    assert out["rate_limit_resets_at"] == just_past
    assert out["rate_limit_7d_pct"] == 12
    assert out["rate_limit_7d_resets_at"] == just_past


def test_fresh_stdin_preserves_pct_when_window_still_active(monkeypatch, isolated_cache):
    """resets_at in the future → render verbatim."""
    now = _time.time()
    future = int(now + 3600)
    _stdin_with({
        "rate_limits": {
            "five_hour": {"used_percentage": 47, "resets_at": future},
        },
    }, monkeypatch)
    out = core.parse_stdin_data()
    assert out["rate_limit_pct"] == 47
    assert out["rate_limit_resets_at"] == future


def test_cached_fallback_expired_window_returns_none(monkeypatch, isolated_cache, tmp_path):
    """When current stdin lacks rate_limits and the cached value's window
    has expired, render unknown (None → '--'), not authoritative 0%."""
    cache_dir = tmp_path / ".cache" / "claude-statusbar"
    cache_dir.mkdir(parents=True)
    now = _time.time()
    expired = int(now - 3600)
    cache_path = cache_dir / "last_stdin.json"
    cache_path.write_text(json.dumps({
        "rate_limits": {
            "five_hour": {"used_percentage": 99, "resets_at": expired},
        },
    }), encoding="utf-8")
    # Cache mtime must be fresh so the age gate doesn't skip the read.
    os.utime(cache_path, (now, now))

    _stdin_with({"session_id": "abc"}, monkeypatch)
    out = core.parse_stdin_data()
    assert out.get("rate_limit_pct") is None, "expired cached pct must not render as 0%"
    assert out.get("rate_limit_resets_at", 0) > now


def test_cached_fallback_active_window_renders_pct(monkeypatch, isolated_cache, tmp_path):
    """Cache fallback with a still-active window renders the cached pct."""
    cache_dir = tmp_path / ".cache" / "claude-statusbar"
    cache_dir.mkdir(parents=True)
    now = _time.time()
    future = int(now + 1800)
    cache_path = cache_dir / "last_stdin.json"
    cache_path.write_text(json.dumps({
        "rate_limits": {
            "five_hour": {"used_percentage": 47, "resets_at": future},
        },
    }), encoding="utf-8")
    os.utime(cache_path, (now, now))

    _stdin_with({"session_id": "abc"}, monkeypatch)
    out = core.parse_stdin_data()
    assert out["rate_limit_pct"] == 47
    assert out["rate_limit_resets_at"] == future


def test_cached_fallback_skipped_when_cache_too_old(monkeypatch, isolated_cache, tmp_path):
    """A cache file older than LAST_STDIN_FALLBACK_MAX_AGE_S (5 min) must
    not be read — its values would be misleading regardless of rollover."""
    cache_dir = tmp_path / ".cache" / "claude-statusbar"
    cache_dir.mkdir(parents=True)
    now = _time.time()
    future = int(now + 1800)
    cache_path = cache_dir / "last_stdin.json"
    cache_path.write_text(json.dumps({
        "rate_limits": {
            "five_hour": {"used_percentage": 99, "resets_at": future},
        },
    }), encoding="utf-8")
    # Backdate cache mtime to 10 minutes ago.
    old = now - 600
    os.utime(cache_path, (old, old))

    _stdin_with({"session_id": "abc"}, monkeypatch)
    out = core.parse_stdin_data()
    assert out.get("rate_limit_pct") is None
    assert out.get("rate_limit_resets_at") is None
