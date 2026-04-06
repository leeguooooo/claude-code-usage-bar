import sys

import claude_statusbar.cli as cli


def test_cli_passes_hide_pet_effort_and_thresholds(monkeypatch):
    captured = {}

    def fake_statusbar_main(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(cli, "statusbar_main", fake_statusbar_main)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "cs",
            "--hide-pet",
            "--warning-threshold",
            "40",
            "--critical-threshold",
            "85",
        ],
    )

    assert cli.main() == 0
    assert captured["show_pet"] is False
    assert captured["warning_threshold"] == 40.0
    assert captured["critical_threshold"] == 85.0


def test_cli_uses_env_fallbacks(monkeypatch):
    captured = {}

    def fake_statusbar_main(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(cli, "statusbar_main", fake_statusbar_main)
    monkeypatch.setenv("CLAUDE_STATUSBAR_HIDE_PET", "1")
    monkeypatch.setenv("CLAUDE_STATUSBAR_WARNING_THRESHOLD", "35")
    monkeypatch.setenv("CLAUDE_STATUSBAR_CRITICAL_THRESHOLD", "75")
    monkeypatch.setattr(sys, "argv", ["cs"])

    assert cli.main() == 0
    assert captured["show_pet"] is False
    assert captured["warning_threshold"] == 35.0
    assert captured["critical_threshold"] == 75.0


def test_cli_rejects_invalid_thresholds(monkeypatch, capsys):
    called = False

    def fake_statusbar_main(**kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(cli, "statusbar_main", fake_statusbar_main)
    monkeypatch.setattr(
        sys, "argv", ["cs", "--warning-threshold", "90", "--critical-threshold", "60"]
    )

    assert cli.main() == 1
    assert called is False
    assert "Thresholds must satisfy" in capsys.readouterr().err
