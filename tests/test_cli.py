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


def test_no_color_env_var_with_any_value(monkeypatch):
    """no-color.org spec: NO_COLOR is honored regardless of value, including
    empty string. We previously only triggered on '1/true/yes' which broke
    the spec."""
    captured = {}

    def fake_statusbar_main(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(cli, "statusbar_main", fake_statusbar_main)
    monkeypatch.setattr(sys, "argv", ["cs"])

    for val in ("", "0", "false", "1", "anything"):
        captured.clear()
        monkeypatch.setenv("NO_COLOR", val)
        cli.main()
        assert captured["use_color"] is False, (
            f"NO_COLOR={val!r} did not disable color"
        )


def test_no_color_unset_keeps_color(monkeypatch):
    captured = {}

    def fake_statusbar_main(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(cli, "statusbar_main", fake_statusbar_main)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(sys, "argv", ["cs"])
    cli.main()
    assert captured["use_color"] is True
