import sys

import claude_statusbar.cli as cli


def test_cli_passes_thresholds(monkeypatch):
    captured = {}

    def fake_statusbar_main(**kwargs):
        captured.update(kwargs)

    import claude_statusbar.core as _core; monkeypatch.setattr(_core, "main", fake_statusbar_main)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "cs",
            "--warning-threshold",
            "40",
            "--critical-threshold",
            "85",
        ],
    )

    assert cli.main() == 0
    assert captured["warning_threshold"] == 40.0
    assert captured["critical_threshold"] == 85.0


def test_cli_uses_env_fallbacks(monkeypatch):
    captured = {}

    def fake_statusbar_main(**kwargs):
        captured.update(kwargs)

    import claude_statusbar.core as _core; monkeypatch.setattr(_core, "main", fake_statusbar_main)
    monkeypatch.setenv("CLAUDE_STATUSBAR_WARNING_THRESHOLD", "35")
    monkeypatch.setenv("CLAUDE_STATUSBAR_CRITICAL_THRESHOLD", "75")
    monkeypatch.setattr(sys, "argv", ["cs"])

    assert cli.main() == 0
    assert captured["warning_threshold"] == 35.0
    assert captured["critical_threshold"] == 75.0


def test_cli_rejects_invalid_thresholds(monkeypatch, capsys):
    called = False

    def fake_statusbar_main(**kwargs):
        nonlocal called
        called = True

    import claude_statusbar.core as _core; monkeypatch.setattr(_core, "main", fake_statusbar_main)
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

    import claude_statusbar.core as _core; monkeypatch.setattr(_core, "main", fake_statusbar_main)
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

    import claude_statusbar.core as _core; monkeypatch.setattr(_core, "main", fake_statusbar_main)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(sys, "argv", ["cs"])
    cli.main()
    assert captured["use_color"] is True


def test_subcommand_skips_heavy_imports(monkeypatch):
    """`cs config show` and friends must not pull in core/styles/themes
    at module import time. Regression test for the lazy-import refactor —
    if someone re-adds `from .core import main` at the top of cli.py, this
    test catches it.

    NOTE: restores sys.modules at the end. Without restoration, other test
    files that did `from claude_statusbar import X` at collection time end
    up with dangling references when their tests run after this one.
    """
    import importlib, sys as _sys

    saved = {k: v for k, v in _sys.modules.items()
             if k.startswith("claude_statusbar")}
    try:
        for k in saved:
            del _sys.modules[k]

        importlib.import_module("claude_statusbar.cli")
        forbidden = {"claude_statusbar.core", "claude_statusbar.themes",
                     "claude_statusbar.styles", "claude_statusbar.progress"}
        leaked = forbidden & set(_sys.modules)
        assert not leaked, f"cli.py imports leaked at module load: {leaked}"
    finally:
        for k in list(_sys.modules):
            if k.startswith("claude_statusbar"):
                del _sys.modules[k]
        _sys.modules.update(saved)


def test_config_reset_removes_file(monkeypatch, tmp_path):
    """`cs config reset` deletes the config file. Idempotent on missing."""
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text('{"style": "capsule"}', encoding="utf-8")

    from claude_statusbar import config as cfg_mod
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", cfg_path)

    monkeypatch.setattr(sys, "argv", ["cs", "config", "reset"])
    assert cli.main() == 0
    assert not cfg_path.exists()

    # second run on missing file must also succeed
    monkeypatch.setattr(sys, "argv", ["cs", "config", "reset"])
    assert cli.main() == 0


def test_config_reset_unknown_action_returns_2(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["cs", "config", "frobnicate"])
    rc = cli.main()
    assert rc == 2
    err = capsys.readouterr().err
    assert "unknown config action" in err
    assert "reset" in err  # the help line should mention it now
