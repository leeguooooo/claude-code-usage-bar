"""Accounts without a 5-hour limit get seven_day alone in rate_limits."""
import io
import json

import pytest

from claude_statusbar import core
from claude_statusbar.styles import render
from claude_statusbar.themes import get_theme


def _parse(monkeypatch, payload):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    monkeypatch.setattr("sys.stdin.isatty", lambda: False, raising=False)
    return core.parse_stdin_data()


def test_seven_day_alone_means_no_limit(monkeypatch):
    data = _parse(monkeypatch, {"rate_limits": {
        "seven_day": {"used_percentage": 67, "resets_at": 9999999999}}})
    assert data["no_five_hour_limit"] is True


def test_both_windows_keep_5h(monkeypatch):
    data = _parse(monkeypatch, {"rate_limits": {
        "five_hour": {"used_percentage": 1, "resets_at": 9999999999},
        "seven_day": {"used_percentage": 67, "resets_at": 9999999999}}})
    assert data["no_five_hour_limit"] is False


def test_unknown_quota_is_not_no_limit(monkeypatch):
    data = _parse(monkeypatch, {"session_id": "fresh"})
    assert not data.get("no_five_hour_limit")


def test_cached_snapshot_keeps_5h_hidden_before_first_reply(monkeypatch):
    monkeypatch.setattr("claude_statusbar.quota_cache.read", lambda data: {
        "seven_day": {"used_percentage": 67, "resets_at": 9999999999}})
    data = _parse(monkeypatch, {"session_id": "fresh"})
    assert data["no_five_hour_limit"] is True


@pytest.mark.parametrize("style", ["aurora", "classic"])
@pytest.mark.parametrize("width", [200, 30])
def test_styles_hide_only_5h(style, width):
    out = render(style, msgs_pct=None, weekly_pct=67, reset_5h="--",
                 reset_7d="8h49m", model="Opus 5.5", use_color=False,
                 theme=get_theme("graphite"), hide_5h=True, max_width=width,
                 narrow_layout="stack")
    assert "5h" not in out
    assert "7d" in out and "67%" in out
