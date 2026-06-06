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


def _payload_with_limits(session_id, used_5h, reset_5h, used_7d, reset_7d):
    return json.dumps({
        "session_id": session_id,
        "transcript_path": "/n.jsonl",
        "model": {"id": "o", "display_name": "Opus 4.8"},
        "rate_limits": {
            "five_hour": {"used_percentage": used_5h, "resets_at": reset_5h},
            "seven_day": {"used_percentage": used_7d, "resets_at": reset_7d},
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


def test_core_renders_reconciled_account_rate_limits(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    config_path = _write_config(tmp_path, show_projection=False, show_forecast=False)
    import claude_statusbar.config as config
    monkeypatch.setattr(config, "CONFIG_PATH", config_path)

    from claude_statusbar.core import main
    import time
    # Plausible near-future resets (a far-future sentinel like 9999999999 is now
    # rejected by reconcile_account's poison guard).
    reset_5h = time.time() + 3600
    reset_7d = time.time() + 6 * 86400

    monkeypatch.setattr(
        sys, "stdin",
        io.StringIO(_payload_with_limits("fresh", 20, reset_5h, 30, reset_7d)),
    )
    main(use_color=False, _suppress_side_effects=True)
    capsys.readouterr()

    monkeypatch.setattr(
        sys, "stdin",
        io.StringIO(_payload_with_limits("stale", 10, reset_5h, 25, reset_7d)),
    )
    main(use_color=False, _suppress_side_effects=True)

    out = capsys.readouterr().out
    assert "20%" in out
    assert "30%" in out
    assert "10%" not in out
    assert "25%" not in out
