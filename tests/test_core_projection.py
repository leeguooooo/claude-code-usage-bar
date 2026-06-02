import io
import json
import sys


def _payload():
    return json.dumps({
        "session_id": "x",
        "transcript_path": "/n.jsonl",
        "model": {"id": "o", "display_name": "Opus 4.8"},
        "rate_limits": {
            "five_hour": {"used_percentage": 17, "resets_at": 9999999999},
            "seven_day": {"used_percentage": 9, "resets_at": 9999999999},
        },
    })


def _write_config(tmp_path, **values):
    (tmp_path / ".claude").mkdir(parents=True)
    base = {
        "show_projection": True,
        "show_forecast": False,
        "show_project_branch": False,
        "show_cache_age": False,
        "show_todos": False,
    }
    base.update(values)
    path = tmp_path / ".claude" / "claude-statusbar.json"
    path.write_text(
        json.dumps(base), encoding="utf-8"
    )
    return path


def test_core_renders_projection_when_enabled(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    config_path = _write_config(tmp_path, show_projection=True)
    import claude_statusbar.config as config
    monkeypatch.setattr(config, "CONFIG_PATH", config_path)
    import claude_statusbar.predict as predict
    monkeypatch.setattr(predict, "projection", lambda *a, **k: ("→50%", "→90%"))
    monkeypatch.setattr(sys, "stdin", io.StringIO(_payload()))

    from claude_statusbar.core import main
    main(use_color=False, _suppress_side_effects=True)

    out = capsys.readouterr().out
    assert "→50%" in out
    assert "→90%" in out


def test_core_hides_projection_when_disabled(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    config_path = _write_config(tmp_path, show_projection=False)
    import claude_statusbar.config as config
    monkeypatch.setattr(config, "CONFIG_PATH", config_path)
    import claude_statusbar.predict as predict
    monkeypatch.setattr(predict, "projection", lambda *a, **k: ("→50%", "→90%"))
    monkeypatch.setattr(sys, "stdin", io.StringIO(_payload()))

    from claude_statusbar.core import main
    main(use_color=False, _suppress_side_effects=True)

    out = capsys.readouterr().out
    assert "→50%" not in out
    assert "→90%" not in out
