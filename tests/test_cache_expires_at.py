"""Prompt-cache countdown from Claude Code's own stdin `prompt_cache.expires_at`.

The transcript only records the user's own turns, so a request that never
reaches it (e.g. a plugin forking the conversation to keep the cache warm)
used to leave the countdown at COLD while the cache was still warm.
"""

import io
import json
import sys
import time

from claude_statusbar import core
from claude_statusbar.activity import format_cache_remaining


def _parse(monkeypatch, payload):
    fake = io.StringIO(json.dumps(payload))
    fake.isatty = lambda: False
    monkeypatch.setattr(sys, "stdin", fake)
    return core.parse_stdin_data()


def test_parse_keeps_prompt_cache_expires_at(monkeypatch):
    parsed = _parse(monkeypatch, {"prompt_cache": {"expires_at": 1791779699}})
    assert parsed["prompt_cache_expires_at"] == 1791779699.0


def test_parse_ignores_missing_or_bad_expires_at(monkeypatch):
    for payload in ({}, {"prompt_cache": None}, {"prompt_cache": {}},
                    {"prompt_cache": {"expires_at": "soon"}},
                    {"prompt_cache": {"expires_at": True}}):
        assert "prompt_cache_expires_at" not in _parse(monkeypatch, payload)


def test_remaining_formats_like_the_transcript_countdown():
    assert format_cache_remaining(3000) == "50m00s"
    assert format_cache_remaining(3600) == "1h00m00s"
    assert format_cache_remaining(42) == "42s"


def test_remaining_is_cold_once_expired():
    assert format_cache_remaining(0) == "COLD"
    assert format_cache_remaining(-5) == "COLD"


def test_render_prefers_expires_at_over_an_old_transcript(tmp_path, monkeypatch, capsys):
    """Last assistant turn 61 min ago (transcript says COLD), but Claude Code
    reports the cache refreshed and valid for 50 more minutes."""
    transcript = tmp_path / "t.jsonl"
    old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 61 * 60))
    transcript.write_text(json.dumps({"type": "assistant", "timestamp": old}) + "\n")
    payload = {
        "session_id": "s",
        "transcript_path": str(transcript),
        "model": {"id": "claude-opus-5-5", "display_name": "Opus"},
        "prompt_cache": {"expires_at": time.time() + 50 * 60, "ttl": "1h"},
    }
    fake = io.StringIO(json.dumps(payload))
    fake.isatty = lambda: False
    monkeypatch.setattr(sys, "stdin", fake)
    monkeypatch.setenv("HOME", str(tmp_path))
    core.main(use_color=False, _suppress_side_effects=True)
    out = capsys.readouterr().out
    assert "COLD" not in out
    assert "cache 49m" in out or "cache 50m" in out, out
