"""End-to-end main() tests for no-quota mode.

Drives core.main() with stdin + a monkeypatched environment, asserting the
rendered classic line switches between the quota layout (5h/7d bars) and the
no-quota layout (ctx bar) based on ANTHROPIC_BASE_URL / CS_API_MODE.
"""

import io
import json
import sys


def _payload_with_quota():
    """A payload that DOES carry official rate_limits + a context window."""
    return json.dumps({
        "session_id": "nq",
        "transcript_path": "/n.jsonl",
        "model": {"id": "o", "display_name": "Opus 4.8"},
        "rate_limits": {
            "five_hour": {"used_percentage": 42, "resets_at": 9999999999},
            "seven_day": {"used_percentage": 18, "resets_at": 9999999999},
        },
        "context_window": {"used_percentage": 35, "context_window_size": 1000000,
                           "total_input_tokens": 350000},
    })


def _write_config(tmp_path, **values):
    (tmp_path / ".claude").mkdir(parents=True)
    base = {
        "show_project_branch": False,
        "show_cache_age": False,
        "show_todos": False,
        "show_mode": False,
    }
    base.update(values)
    path = tmp_path / ".claude" / "claude-statusbar.json"
    path.write_text(json.dumps(base), encoding="utf-8")
    return path


def _run(tmp_path, monkeypatch, payload):
    monkeypatch.setenv("HOME", str(tmp_path))
    config_path = _write_config(tmp_path)
    import claude_statusbar.config as config
    monkeypatch.setattr(config, "CONFIG_PATH", config_path)
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    from claude_statusbar.core import main
    main(use_color=False, _suppress_side_effects=True)


def test_relay_env_forces_no_quota_layout(tmp_path, monkeypatch, capsys):
    """ANTHROPIC_BASE_URL relay → ctx bar, quota bars suppressed even though the
    payload carried rate_limits (they aren't the official quota on a relay)."""
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://relay.example.com")
    monkeypatch.delenv("CS_API_MODE", raising=False)
    _run(tmp_path, monkeypatch, _payload_with_quota())
    out = capsys.readouterr().out
    assert "ctx[" in out
    assert "5h[" not in out
    assert "7d[" not in out


def test_official_env_keeps_quota_layout(tmp_path, monkeypatch, capsys):
    """No relay env → unchanged: 5h/7d bars render, no ctx bar."""
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("CS_API_MODE", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_USE_BEDROCK", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_USE_VERTEX", raising=False)
    _run(tmp_path, monkeypatch, _payload_with_quota())
    out = capsys.readouterr().out
    assert "5h[" in out
    assert "ctx[" not in out


def test_cs_api_mode_off_overrides_relay_env(tmp_path, monkeypatch, capsys):
    """CS_API_MODE=off forces the official layout back even on a relay."""
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://relay.example.com")
    monkeypatch.setenv("CS_API_MODE", "off")
    _run(tmp_path, monkeypatch, _payload_with_quota())
    out = capsys.readouterr().out
    assert "5h[" in out
    assert "ctx[" not in out


def _payload_no_quota_with_transcript(tp):
    """No rate_limits at all (relay stripped them), but a real transcript path."""
    return json.dumps({
        "session_id": "nqh",
        "transcript_path": tp,
        "model": {"id": "o", "display_name": "Opus 4.8"},
        "context_window": {"used_percentage": 35, "context_window_size": 1000000,
                           "total_input_tokens": 350000},
    })


def test_heuristic_switches_layout_without_env(tmp_path, monkeypatch, capsys):
    """No relay env, no quota, but the transcript has an assistant turn →
    heuristic flips to the ctx layout (insurance for un-inherited env)."""
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("CS_API_MODE", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_USE_BEDROCK", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_USE_VERTEX", raising=False)
    tp = tmp_path / "t.jsonl"
    tp.write_text(json.dumps({
        "type": "assistant", "timestamp": "2999-01-01T00:00:00.000Z",
        "message": {"usage": {"input_tokens": 10, "output_tokens": 5}},
    }) + "\n", encoding="utf-8")
    _run(tmp_path, monkeypatch, _payload_no_quota_with_transcript(str(tp)))
    out = capsys.readouterr().out
    assert "ctx[" in out
    assert "5h[" not in out


def test_heuristic_silent_with_empty_transcript(tmp_path, monkeypatch, capsys):
    """No env, no quota, transcript has NO assistant turn yet → stay in the
    waiting/quota layout (don't prematurely switch at session start)."""
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("CS_API_MODE", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_USE_BEDROCK", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_USE_VERTEX", raising=False)
    tp = tmp_path / "empty.jsonl"
    tp.write_text(json.dumps({"type": "user", "timestamp": "2999-01-01T00:00:00Z"}) + "\n",
                  encoding="utf-8")
    _run(tmp_path, monkeypatch, _payload_no_quota_with_transcript(str(tp)))
    out = capsys.readouterr().out
    assert "ctx[" not in out
