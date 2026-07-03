"""Issue #30: opt-in `show_cwd` working-directory segment.

Config: `show_cwd` (bool, default False) + `cwd_style` ("basename" | "full").
Render: the directory rides the identity line when show_project_branch is on
(skipped when it just repeats the project name), else gets its own `⤷` line.
"""

from pathlib import Path

import pytest

from claude_statusbar import config
from claude_statusbar.identity import IdentityInfo
from claude_statusbar.styles import render, render_identity_line
from claude_statusbar.themes import get_theme


THEME = get_theme("graphite")


def _info(name="proj"):
    return IdentityInfo(project_name=name, in_git=True, branch="main",
                        detached=False, worktree_name=None, toplevel="/x")


# --- config -------------------------------------------------------------------

def test_show_cwd_defaults_off():
    cfg = config.StatusbarConfig()
    assert cfg.show_cwd is False
    assert cfg.cwd_style == "basename"


def test_show_cwd_roundtrip(tmp_path: Path):
    p = tmp_path / "cfg.json"
    cfg = config.StatusbarConfig(show_cwd=True, cwd_style="full")
    config.save_config(cfg, p)
    loaded = config.load_config(p)
    assert loaded.show_cwd is True
    assert loaded.cwd_style == "full"


def test_set_value_show_cwd(tmp_path: Path):
    p = tmp_path / "cfg.json"
    cfg = config.set_value("show_cwd", "true", p)
    assert cfg.show_cwd is True
    cfg = config.set_value("show_cwd", "off", p)
    assert cfg.show_cwd is False


def test_set_value_cwd_style_validates(tmp_path: Path):
    p = tmp_path / "cfg.json"
    cfg = config.set_value("cwd_style", "full", p)
    assert cfg.cwd_style == "full"
    with pytest.raises(ValueError):
        config.set_value("cwd_style", "fancy", p)


def test_keys_registered():
    assert "show_cwd" in config.VALID_KEYS
    assert "cwd_style" in config.VALID_KEYS
    assert "show_cwd" in config._BOOL_KEYS


# --- identity-line rendering ----------------------------------------------------

def test_cwd_on_identity_line():
    s = render_identity_line(_info(), theme=THEME, dirty=False,
                             cwd_text="subdir", use_color=False)
    assert "· subdir" in s


def test_cwd_skipped_when_it_repeats_project_name():
    # cwd at the repo root — the project name already says it.
    s = render_identity_line(_info("proj"), theme=THEME, dirty=False,
                             cwd_text="proj", use_color=False)
    assert "· proj" not in s


def test_cwd_full_path_always_shows():
    s = render_identity_line(_info("proj"), theme=THEME, dirty=False,
                             cwd_text="/repos/proj", use_color=False)
    assert "· /repos/proj" in s


def test_no_cwd_text_no_segment():
    s = render_identity_line(_info(), theme=THEME, dirty=False,
                             use_color=False)
    assert "·" not in s.replace("· v", "")  # only the version separator allowed


# --- full render plumbing -------------------------------------------------------

_BASE = dict(msgs_pct=10, weekly_pct=5, reset_5h="1h00m", reset_7d="2d00h",
             model="Test", lang_body="", use_color=False, theme=THEME)


def test_render_passes_cwd_to_identity_line():
    out = render("classic", **_BASE,
                 show_project_branch=True, identity=_info(),
                 identity_dirty=False, cwd_text="subdir")
    lines = out.split("\n")
    assert any("⤷" in ln and "· subdir" in ln for ln in lines)


def test_render_standalone_cwd_line_when_identity_off():
    out = render("classic", **_BASE, cwd_text="subdir")
    assert "\n⤷ subdir" in out


def test_render_without_cwd_adds_no_extra_line():
    with_none = render("classic", **_BASE)
    assert "⤷" not in with_none
