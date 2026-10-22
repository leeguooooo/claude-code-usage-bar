"""`cs theme` — interactive picker over the three looks."""

import sys

import pytest

from claude_statusbar import config as cfg_mod
from claude_statusbar import picker


@pytest.fixture
def live_cfg(tmp_path, monkeypatch):
    p = tmp_path / "c.json"
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", p)
    p.write_text('{"lang": "zh"}', encoding="utf-8")
    monkeypatch.setattr("claude_statusbar.preview._real_data", lambda: None)
    return p


@pytest.mark.parametrize("style,glyph,want", [
    ("aurora", "block", "block"), ("aurora", "thin", "thin"),
    ("classic", "thin", "classic"),
])
def test_current_look(style, glyph, want):
    assert picker.current_look(cfg_mod.StatusbarConfig(style=style, bar_glyph=glyph)) == want


@pytest.mark.parametrize("key,style,glyph", [
    ("block", "aurora", "block"), ("thin", "aurora", "thin"), ("classic", "classic", None),
])
def test_apply_sets_the_look(live_cfg, key, style, glyph):
    picker.apply(key)
    cfg = cfg_mod.load_config()
    assert cfg.style == style
    if glyph:
        assert cfg.bar_glyph == glyph
    assert picker.current_look(cfg) == key


def test_non_tty_lists_three_previews_and_marks_current(live_cfg, capsys):
    cfg_mod.set_value("bar_glyph", "thin")
    assert picker.run(no_color=True) == 0
    out = capsys.readouterr().out
    assert "■" in out and "━" in out and "5h[" in out
    thin_line = next(line for line in out.splitlines() if "Aurora 细线" in line)
    assert "← 当前" in thin_line


def test_numbered_fallback_picks_by_number(live_cfg, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _prompt: "3")
    assert picker._numbered("block", ["a", "b", "c"], False) == "classic"
    monkeypatch.setattr("builtins.input", lambda _prompt: "")
    assert picker._numbered("block", ["a", "b", "c"], False) is None


def test_cli_routes_theme_to_picker(live_cfg, monkeypatch, capsys):
    from claude_statusbar import cli
    for word in ("theme", "themes", "looks"):
        monkeypatch.setattr(sys, "argv", ["cs", word, "--no-color"])
        assert cli.main() == 0
        assert "Aurora 方块" in capsys.readouterr().out


def test_english_ui(live_cfg, capsys):
    cfg_mod.set_value("lang", "en")
    picker.run(no_color=True)
    out = capsys.readouterr().out
    assert "Aurora, block bars (default)" in out and "← current" in out
    assert "方块" not in out
