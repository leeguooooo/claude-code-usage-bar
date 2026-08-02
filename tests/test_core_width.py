import io
import json
import os
import sys

import pytest

from claude_statusbar._display import visible_width


def _payload(session_env):
    return json.dumps({
        "session_id": "width",
        "version": "2.1.220",
        "model": {"id": "claude-opus-5", "display_name": "Opus 5"},
        "rate_limits": {
            "five_hour": {"used_percentage": 42, "resets_at": 9999999999},
            "seven_day": {"used_percentage": 18, "resets_at": 9999999999},
        },
        "context_window": {
            "used_percentage": 6,
            "context_window_size": 1_000_000,
            "current_usage": {
                "input_tokens": 40_000,
                "cache_creation_input_tokens": 3_824,
                "cache_read_input_tokens": 20_000,
                "output_tokens": 999_999,
            },
        },
        "_cs_env": session_env,
    })


def _run(tmp_path, monkeypatch, capsys, session_env, terminal_width=None):
    config_path = tmp_path / ".claude" / "claude-statusbar.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps({
        "style": "classic",
        "auto_compact_width": 60,
        "show_project_branch": False,
        "show_cache_age": False,
        "show_todos": False,
        "show_mode": False,
        "show_party": False,
        "show_version": False,
    }), encoding="utf-8")

    import claude_statusbar.config as config
    import claude_statusbar.styles as styles
    from claude_statusbar import _display
    from claude_statusbar.core import main

    monkeypatch.setattr(config, "CONFIG_PATH", config_path)
    if terminal_width is None:
        def unavailable():
            raise OSError
        monkeypatch.setattr(_display.os, "get_terminal_size", unavailable)
    else:
        monkeypatch.setattr(
            _display.os, "get_terminal_size",
            lambda: os.terminal_size((terminal_width, 24)),
        )
    monkeypatch.setattr(sys, "stdin", io.StringIO(_payload(session_env)))

    seen = {}
    original = styles.render

    def capture(style, **kwargs):
        seen["style"] = style
        seen["max_width"] = kwargs.get("max_width")
        return original(style, **kwargs)

    monkeypatch.setattr(styles, "render", capture)
    main(use_color=False, _suppress_side_effects=True)
    return seen, capsys.readouterr().out


@pytest.mark.parametrize("session_env", [
    {"COLUMNS": "36"},
    {"COLUMNS": "36", "ANTHROPIC_BASE_URL": "http://127.0.0.1:17870"},
])
def test_session_columns_drives_auto_compact_and_hard_cap(
        tmp_path, monkeypatch, capsys, session_env):
    seen, out = _run(tmp_path, monkeypatch, capsys, session_env)
    assert seen == {"style": "hairline", "max_width": 36}
    assert all(visible_width(line) <= 36 for line in out.splitlines())


@pytest.mark.parametrize("bad", ["", "0", "-5", "nope"])
def test_invalid_columns_uses_terminal_fallback(
        tmp_path, monkeypatch, capsys, bad):
    seen, out = _run(
        tmp_path, monkeypatch, capsys, {"COLUMNS": bad}, terminal_width=50)
    assert seen == {"style": "hairline", "max_width": 50}
    assert all(visible_width(line) <= 50 for line in out.splitlines())


def test_unavailable_width_preserves_unbounded_style(
        tmp_path, monkeypatch, capsys):
    seen, out = _run(tmp_path, monkeypatch, capsys, {"COLUMNS": "bad"})
    assert seen == {"style": "classic", "max_width": None}
    assert out
