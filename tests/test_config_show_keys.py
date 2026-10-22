"""`cs config show` must list every togglable key, including the identity /
activity flags (regression: the display list was hardcoded and omitted them)."""

import sys

from claude_statusbar import cli


def test_config_show_lists_all_show_flags(capsys, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["cs", "config", "show"])
    rc = cli.main()
    out = capsys.readouterr().out
    assert rc == 0
    for key in ("show_project_branch", "show_ahead_behind", "show_todos",
                "show_tools", "show_tool_rollup", "show_agents",
                "show_duration", "show_lines", "show_forecast"):
        assert key in out, f"{key} missing from `cs config show`"


def test_show_marks_values_that_are_only_defaults(capsys, monkeypatch, tmp_path):
    # A chosen value and a default look identical without this — the ambiguity
    # that hid a stale `show_project_branch = False` after the default flipped.
    from claude_statusbar import config as cfg_mod
    p = tmp_path / "c.json"
    cfg_mod.set_value("bar_glyph", "thin", p)
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", p)

    monkeypatch.setattr(sys, "argv", ["cs", "config", "show"])
    assert cli.main() == 0
    out = capsys.readouterr().out

    glyph_line = next(l for l in out.splitlines() if l.startswith("bar_glyph"))
    style_line = next(l for l in out.splitlines() if l.startswith("style"))
    assert "thin" in glyph_line and "(default)" not in glyph_line
    assert "(default)" in style_line


def test_unset_subcommand_clears_a_key(capsys, monkeypatch, tmp_path):
    from claude_statusbar import config as cfg_mod
    import json
    p = tmp_path / "c.json"
    cfg_mod.set_value("bar_glyph", "thin", p)
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", p)

    monkeypatch.setattr(sys, "argv", ["cs", "config", "unset", "bar_glyph"])
    assert cli.main() == 0
    assert "following the default" in capsys.readouterr().out
    from claude_statusbar.config import UI_VERSION, LOOKS_VERSION
    # bar_glyph is gone; choosing it once also recorded the looks as seen.
    assert json.loads(p.read_text()) == {"ui_version": UI_VERSION,
                                         "looks_seen": LOOKS_VERSION}


def test_unset_rejects_unknown_key(capsys, monkeypatch, tmp_path):
    from claude_statusbar import config as cfg_mod
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", tmp_path / "c.json")
    monkeypatch.setattr(sys, "argv", ["cs", "config", "unset", "nope"])
    assert cli.main() == 2
    assert "unknown config key" in capsys.readouterr().err
