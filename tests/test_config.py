"""Tests for ~/.claude/claude-statusbar.json read/write/resolve."""

import json
from pathlib import Path

import pytest

from claude_statusbar import config as cfg_mod


def test_load_returns_defaults_when_missing(tmp_path: Path):
    cfg = cfg_mod.load_config(tmp_path / "missing.json")
    assert cfg.style == cfg_mod.DEFAULT_STYLE
    assert cfg.theme == cfg_mod.DEFAULT_THEME
    assert cfg.density == cfg_mod.DEFAULT_DENSITY
    assert cfg.show_pet is True
    assert cfg.show_weekly is True
    assert cfg.show_language is True


def test_load_returns_defaults_for_garbage(tmp_path: Path):
    p = tmp_path / "broken.json"
    p.write_text("not json", encoding="utf-8")
    cfg = cfg_mod.load_config(p)
    assert cfg.style == cfg_mod.DEFAULT_STYLE


def test_save_then_load_roundtrip(tmp_path: Path):
    p = tmp_path / "cfg.json"
    cfg = cfg_mod.StatusbarConfig(style="capsule", theme="twilight",
                                   density="cozy", show_pet=False)
    cfg_mod.save_config(cfg, p)

    raw = json.loads(p.read_text(encoding="utf-8"))
    assert raw["style"] == "capsule"
    assert raw["theme"] == "twilight"
    assert raw["density"] == "cozy"
    assert raw["show_pet"] is False

    loaded = cfg_mod.load_config(p)
    assert loaded == cfg


def test_set_value_persists(tmp_path: Path):
    p = tmp_path / "cfg.json"
    cfg_mod.set_value("style", "hairline", p)
    cfg_mod.set_value("density", "compact", p)
    cfg_mod.set_value("show_weekly", "false", p)
    cfg_mod.set_value("warning_threshold", "25.5", p)
    cfg_mod.set_value("auto_compact_width", "100", p)

    cfg = cfg_mod.load_config(p)
    assert cfg.style == "hairline"
    assert cfg.density == "compact"
    assert cfg.show_weekly is False
    assert cfg.warning_threshold == 25.5
    assert cfg.auto_compact_width == 100


def test_set_value_rejects_unknown_key(tmp_path: Path):
    with pytest.raises(KeyError):
        cfg_mod.set_value("not_a_key", "foo", tmp_path / "cfg.json")


def test_set_value_rejects_non_numeric_threshold(tmp_path: Path):
    with pytest.raises(ValueError):
        cfg_mod.set_value("warning_threshold", "high", tmp_path / "cfg.json")


def test_set_value_rejects_invalid_density(tmp_path: Path):
    with pytest.raises(ValueError):
        cfg_mod.set_value("density", "snug", tmp_path / "cfg.json")


@pytest.mark.parametrize("ok", ["compact", "regular", "cozy"])
def test_set_value_accepts_valid_density(tmp_path: Path, ok: str):
    cfg_mod.set_value("density", ok, tmp_path / "cfg.json")
    assert cfg_mod.load_config(tmp_path / "cfg.json").density == ok


def test_set_value_rejects_invalid_style(tmp_path: Path):
    with pytest.raises(ValueError):
        cfg_mod.set_value("style", "capsulee", tmp_path / "cfg.json")


def test_set_value_rejects_invalid_theme(tmp_path: Path):
    with pytest.raises(ValueError):
        cfg_mod.set_value("theme", "midnight", tmp_path / "cfg.json")


@pytest.mark.parametrize("style", ["classic", "capsule", "hairline"])
def test_set_value_accepts_valid_style(tmp_path: Path, style: str):
    cfg_mod.set_value("style", style, tmp_path / "cfg.json")
    assert cfg_mod.load_config(tmp_path / "cfg.json").style == style


@pytest.mark.parametrize("theme", ["graphite", "twilight", "linen", "nord", "dracula", "sakura", "mono"])
def test_set_value_accepts_valid_theme(tmp_path: Path, theme: str):
    cfg_mod.set_value("theme", theme, tmp_path / "cfg.json")
    assert cfg_mod.load_config(tmp_path / "cfg.json").theme == theme


def test_resolve_style_priority(tmp_path: Path):
    cfg = cfg_mod.StatusbarConfig(style="capsule")
    # CLI wins
    assert cfg_mod.resolve_style("hairline", cfg) == "hairline"
    # Else env var
    import os
    os.environ["CLAUDE_STATUSBAR_STYLE"] = "classic"
    try:
        assert cfg_mod.resolve_style(None, cfg) == "classic"
    finally:
        del os.environ["CLAUDE_STATUSBAR_STYLE"]
    # Else config
    assert cfg_mod.resolve_style(None, cfg) == "capsule"


def test_to_bool_handles_strings_and_bools():
    for truthy in (True, "1", "true", "yes", "on", "Y"):
        assert cfg_mod._to_bool(truthy) is True
    for falsy in (False, "0", "false", "no", "off", ""):
        assert cfg_mod._to_bool(falsy) is False


def test_save_config_is_atomic(tmp_path: Path):
    """Two writes must not leave a .tmp file behind, and second write must
    succeed (regression: config.save_config used to call write_text directly,
    so Ctrl+C mid-write could corrupt the JSON file)."""
    p = tmp_path / "cfg.json"
    cfg_mod.save_config(cfg_mod.StatusbarConfig(style="capsule"), p)
    cfg_mod.save_config(cfg_mod.StatusbarConfig(style="hairline"), p)

    leftover = list(tmp_path.glob(".cfg.json.*.tmp"))
    assert leftover == [], f"temp files leaked: {leftover}"

    loaded = cfg_mod.load_config(p)
    assert loaded.style == "hairline"


def test_set_warning_above_default_critical_rejected(tmp_path: Path):
    """Defaults: warning=None→30, critical=None→70. Setting warning=80
    would create an invalid pair (80 >= 70) and crash every render."""
    p = tmp_path / "cfg.json"
    with pytest.raises(ValueError, match="invalid"):
        cfg_mod.set_value("warning_threshold", "80", p)


def test_set_critical_below_warning_rejected(tmp_path: Path):
    """If warning is already 50, setting critical=40 is invalid."""
    p = tmp_path / "cfg.json"
    cfg_mod.set_value("critical_threshold", "60", p)  # 30 < 60 OK
    cfg_mod.set_value("warning_threshold", "50", p)   # 50 < 60 OK
    with pytest.raises(ValueError, match="invalid"):
        cfg_mod.set_value("critical_threshold", "40", p)


def test_thresholds_can_be_widened_in_correct_order(tmp_path: Path):
    """Two-step move: raise ceiling first, then floor."""
    p = tmp_path / "cfg.json"
    cfg_mod.set_value("critical_threshold", "90", p)  # 30 < 90 OK
    cfg_mod.set_value("warning_threshold", "80", p)   # 80 < 90 OK
    cfg = cfg_mod.load_config(p)
    assert cfg.warning_threshold == 80.0
    assert cfg.critical_threshold == 90.0
