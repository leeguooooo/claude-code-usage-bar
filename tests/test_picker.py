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


def test_if_new_is_silent_once_seen(live_cfg, capsys):
    cfg_mod.set_value("looks_seen", str(cfg_mod.LOOKS_VERSION))
    assert picker.run(no_color=True, only_if_new=True) == 0
    assert capsys.readouterr().out == ""


def test_if_new_never_prints_without_a_terminal(live_cfg, capsys):
    # Unseen looks, but piped: the upgrade hook must not dump a list.
    assert picker.run(no_color=True, only_if_new=True) == 0
    assert capsys.readouterr().out == ""


def test_interactive_session_marks_looks_seen(live_cfg, monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(picker, "_interactive", lambda *a: None)  # user cancels
    picker.run(no_color=True)
    assert cfg_mod.load_config().looks_seen == cfg_mod.LOOKS_VERSION


@pytest.mark.parametrize("lang,text", [("zh", "cs theme"), ("en", "New looks")])
def test_bar_shows_hint_only_while_looks_unseen(lang, text):
    from claude_statusbar.styles import render
    kw = dict(msgs_pct=10, weekly_pct=20, reset_5h="1h", reset_7d="2d",
              model="Opus", use_color=False, ui_lang=lang)
    assert text in render("aurora", looks_hint=True, **kw)
    assert "✦" not in render("aurora", looks_hint=False, **kw)


def test_core_passes_hint_from_config(live_cfg, monkeypatch):
    live_cfg.write_text('{"style": "classic", "ui_version": 3}', encoding="utf-8")
    import claude_statusbar.styles as styles
    from claude_statusbar.core import main
    seen = []
    original = styles.render
    monkeypatch.setattr(styles, "render",
                        lambda style, **kw: seen.append(kw.get("looks_hint")) or original(style, **kw))
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO("{}"))
    main(use_color=False, _suppress_side_effects=True)
    cfg_mod.set_value("looks_seen", str(cfg_mod.LOOKS_VERSION))
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO("{}"))
    main(use_color=False, _suppress_side_effects=True)
    assert seen[0] is True and seen[-1] is False


def test_upgrade_offers_picker_in_new_build(monkeypatch):
    from claude_statusbar import cli
    calls = []
    monkeypatch.setattr("claude_statusbar.updater.upgrade_current_install", lambda: (True, "ok"))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
    monkeypatch.setattr("shutil.which", lambda name: "/bin/cs-new")
    monkeypatch.setattr("subprocess.run", lambda args, **kw: calls.append(args))
    assert cli._run_upgrade_subcommand() == 0
    assert calls == [["/bin/cs-new", "theme", "--if-new"]]


@pytest.mark.parametrize("key,value", [("style", "classic"), ("style", "aurora"),
                                       ("bar_glyph", "thin"), ("bar_glyph", "block")])
def test_choosing_a_look_any_way_clears_the_hint(live_cfg, key, value):
    # /statusbar-style, the skill and plain `cs config set` never open the
    # picker; the hint must still go away once a look has been chosen.
    assert cfg_mod.load_config().looks_seen < cfg_mod.LOOKS_VERSION
    cfg_mod.set_value(key, value)
    assert cfg_mod.load_config().looks_seen == cfg_mod.LOOKS_VERSION


def test_default_look_users_get_no_hint(live_cfg, monkeypatch):
    # Still on the default look = already running what's new.
    import claude_statusbar.styles as styles
    from claude_statusbar.core import main
    seen = []
    original = styles.render
    monkeypatch.setattr(styles, "render",
                        lambda style, **kw: seen.append(kw.get("looks_hint")) or original(style, **kw))
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO("{}"))
    main(use_color=False, _suppress_side_effects=True)
    assert cfg_mod.load_config().looks_seen < cfg_mod.LOOKS_VERSION
    assert seen == [False]
