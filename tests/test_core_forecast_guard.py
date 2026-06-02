import io, json, sys


def _write_config(tmp_path, payload):
    (tmp_path / ".claude").mkdir(parents=True)
    path = tmp_path / ".claude" / "claude-statusbar.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_main_survives_forecast_exception(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    config_path = _write_config(tmp_path, {"show_forecast": True, "show_projection": False,
                                           "show_project_branch": False,
                                           "show_cache_age": False, "show_todos": False})
    import claude_statusbar.config as config
    monkeypatch.setattr(config, "CONFIG_PATH", config_path)
    import claude_statusbar.predict as predict
    monkeypatch.setattr(predict, "forecast",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    payload = json.dumps({
        "session_id": "x", "transcript_path": "/n.jsonl",
        "model": {"id": "o", "display_name": "Opus 4.8"},
        "rate_limits": {"five_hour": {"used_percentage": 80, "resets_at": 9999999999},
                        "seven_day": {"used_percentage": 5, "resets_at": 9999999999}}})
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    from claude_statusbar.core import main
    main(use_color=False, _suppress_side_effects=True)
    assert "Opus 4.8" in capsys.readouterr().out   # bar still rendered, no blank


def test_chip_appears_when_forecast_returns_one(tmp_path, monkeypatch, capsys):
    # True RED→GREEN: a non-throwing forecast returning a chip must reach the bar.
    monkeypatch.setenv("HOME", str(tmp_path))
    config_path = _write_config(tmp_path, {"show_forecast": True, "show_projection": False,
                                           "show_project_branch": False,
                                           "show_cache_age": False, "show_todos": False})
    import claude_statusbar.config as config
    monkeypatch.setattr(config, "CONFIG_PATH", config_path)
    import claude_statusbar.predict as predict
    monkeypatch.setattr(predict, "forecast", lambda *a, **k: ("~8m", ""))
    payload = json.dumps({
        "session_id": "x", "transcript_path": "/n.jsonl",
        "model": {"id": "o", "display_name": "Opus 4.8"},
        "rate_limits": {"five_hour": {"used_percentage": 88, "resets_at": 9999999999},
                        "seven_day": {"used_percentage": 5, "resets_at": 9999999999}}})
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    from claude_statusbar.core import main
    main(use_color=False, _suppress_side_effects=True)
    assert "~8m" in capsys.readouterr().out   # chip plumbed to the bar
