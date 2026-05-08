"""Per-severity color overrides — config + theme application.

Users can override `s_ok / s_warn / s_hot` independently of theme via
`cs config set color_ok "#4ec85b"`. The override layers on top of the
resolved theme; ink/mute/edge/pill_* stay from the base theme.
"""
import pytest

from claude_statusbar.themes import (
    apply_color_overrides,
    get_theme,
    parse_hex_color,
)


# ── parse_hex_color ────────────────────────────────────────────────────────

def test_parse_hex_full():
    assert parse_hex_color("#4ec85b") == (78, 200, 91)


def test_parse_hex_no_hash():
    assert parse_hex_color("4ec85b") == (78, 200, 91)


def test_parse_hex_short():
    """Short form '#abc' expands to '#aabbcc'."""
    assert parse_hex_color("#fab") == (255, 170, 187)


def test_parse_hex_uppercase():
    assert parse_hex_color("#4EC85B") == (78, 200, 91)


def test_parse_hex_with_whitespace():
    assert parse_hex_color("  #4ec85b  ") == (78, 200, 91)


def test_parse_hex_rejects_wrong_length():
    with pytest.raises(ValueError, match="hex like"):
        parse_hex_color("#4ec85")  # 5 digits


def test_parse_hex_rejects_invalid_chars():
    with pytest.raises(ValueError, match="invalid hex"):
        parse_hex_color("#zzzzzz")


# ── apply_color_overrides ──────────────────────────────────────────────────

def test_no_override_returns_same_theme():
    base = get_theme("graphite")
    out = apply_color_overrides(base)
    assert out is base


def test_override_only_s_ok():
    base = get_theme("graphite")
    out = apply_color_overrides(base, ok=(78, 200, 91))
    assert out.s_ok == (78, 200, 91)
    # s_warn / s_hot unchanged
    assert out.s_warn == base.s_warn
    assert out.s_hot == base.s_hot
    # ink / mute / edge / pill_* unchanged — overrides scope is severity only
    assert out.ink == base.ink
    assert out.mute == base.mute
    assert out.edge == base.edge
    assert out.pill_5h == base.pill_5h
    assert out.pill_cost == base.pill_cost


def test_override_all_three_severities():
    base = get_theme("nord")
    out = apply_color_overrides(
        base, ok=(1, 1, 1), warn=(2, 2, 2), hot=(3, 3, 3)
    )
    assert out.s_ok == (1, 1, 1)
    assert out.s_warn == (2, 2, 2)
    assert out.s_hot == (3, 3, 3)


def test_override_does_not_mutate_input():
    """The input theme must be untouched — important because BUILTIN_THEMES
    is shared module-level state."""
    base = get_theme("graphite")
    original_s_ok = base.s_ok
    apply_color_overrides(base, ok=(99, 99, 99))
    assert base.s_ok == original_s_ok


def test_override_returns_dataclass():
    """Return value must still be a Theme so renderers can use it."""
    from claude_statusbar.themes import Theme
    base = get_theme("graphite")
    out = apply_color_overrides(base, ok=(78, 200, 91))
    assert isinstance(out, Theme)


# ── config integration ────────────────────────────────────────────────────

def test_config_persists_canonical_hex(tmp_path):
    """set_value normalizes input to canonical lowercase '#rrggbb' form."""
    from claude_statusbar.config import set_value, load_config
    cfg_path = tmp_path / "cfg.json"
    set_value("color_ok", "#4EC85B", path=cfg_path)
    cfg = load_config(cfg_path)
    assert cfg.color_ok == "#4ec85b"


def test_config_short_hex_normalized(tmp_path):
    from claude_statusbar.config import set_value, load_config
    cfg_path = tmp_path / "cfg.json"
    set_value("color_ok", "#fab", path=cfg_path)
    cfg = load_config(cfg_path)
    assert cfg.color_ok == "#ffaabb"


def test_config_empty_string_clears_override(tmp_path):
    from claude_statusbar.config import set_value, load_config
    cfg_path = tmp_path / "cfg.json"
    set_value("color_ok", "#4ec85b", path=cfg_path)
    set_value("color_ok", "", path=cfg_path)
    cfg = load_config(cfg_path)
    assert cfg.color_ok is None


def test_config_invalid_hex_rejected(tmp_path):
    from claude_statusbar.config import set_value
    cfg_path = tmp_path / "cfg.json"
    with pytest.raises(ValueError, match="hex"):
        set_value("color_ok", "not-a-color", path=cfg_path)


def test_config_three_color_keys_independent(tmp_path):
    from claude_statusbar.config import set_value, load_config
    cfg_path = tmp_path / "cfg.json"
    set_value("color_ok", "#111111", path=cfg_path)
    set_value("color_warn", "#222222", path=cfg_path)
    set_value("color_hot", "#333333", path=cfg_path)
    cfg = load_config(cfg_path)
    assert cfg.color_ok == "#111111"
    assert cfg.color_warn == "#222222"
    assert cfg.color_hot == "#333333"
