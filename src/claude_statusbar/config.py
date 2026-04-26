"""User-facing config persisted at ~/.claude/claude-statusbar.json.

Resolution order for any field:
    1. CLI flag        (e.g. --style capsule)
    2. Env var         (e.g. CLAUDE_STATUSBAR_STYLE)
    3. Config file     (~/.claude/claude-statusbar.json)
    4. Built-in default
"""

import json
import os
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Optional

CONFIG_PATH = Path.home() / ".claude" / "claude-statusbar.json"

DEFAULT_STYLE = "classic"     # keep existing behavior for upgraders
DEFAULT_THEME = "graphite"
DEFAULT_DENSITY = "regular"   # cozy | regular | compact
DEFAULT_AUTO_COMPACT_WIDTH = 0  # 0 = disabled; otherwise force hairline below this width


@dataclass
class StatusbarConfig:
    style: str = DEFAULT_STYLE
    theme: str = DEFAULT_THEME
    density: str = DEFAULT_DENSITY
    auto_compact_width: int = DEFAULT_AUTO_COMPACT_WIDTH
    show_pet: bool = True
    show_weekly: bool = True
    show_language: bool = True
    warning_threshold: Optional[float] = None
    critical_threshold: Optional[float] = None


def _to_bool(v):
    if isinstance(v, bool): return v
    s = str(v).strip().lower()
    return s in ("1", "true", "yes", "on", "y", "t")


def load_config(path: Path = CONFIG_PATH) -> StatusbarConfig:
    if not path.exists():
        return StatusbarConfig()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return StatusbarConfig()
    if not isinstance(raw, dict):
        return StatusbarConfig()
    return StatusbarConfig(
        style=str(raw.get("style", DEFAULT_STYLE)),
        theme=str(raw.get("theme", DEFAULT_THEME)),
        density=str(raw.get("density", DEFAULT_DENSITY)),
        auto_compact_width=int(raw.get("auto_compact_width", DEFAULT_AUTO_COMPACT_WIDTH) or 0),
        show_pet=_to_bool(raw.get("show_pet", True)),
        show_weekly=_to_bool(raw.get("show_weekly", True)),
        show_language=_to_bool(raw.get("show_language", True)),
        warning_threshold=raw.get("warning_threshold"),
        critical_threshold=raw.get("critical_threshold"),
    )


def save_config(cfg: StatusbarConfig, path: Path = CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(cfg), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


VALID_KEYS = {
    "style", "theme", "density", "auto_compact_width",
    "show_pet", "show_weekly", "show_language",
    "warning_threshold", "critical_threshold",
}
_BOOL_KEYS = {"show_pet", "show_weekly", "show_language"}
_FLOAT_KEYS = {"warning_threshold", "critical_threshold"}
_INT_KEYS = {"auto_compact_width"}


def set_value(key: str, value: str, path: Path = CONFIG_PATH) -> StatusbarConfig:
    if key not in VALID_KEYS:
        raise KeyError(f"unknown config key: {key} (valid: {sorted(VALID_KEYS)})")
    cfg = load_config(path)
    if key in _FLOAT_KEYS:
        try:
            setattr(cfg, key, float(value))
        except ValueError as e:
            raise ValueError(f"{key} must be a number, got {value!r}") from e
    elif key in _INT_KEYS:
        try:
            setattr(cfg, key, int(value))
        except ValueError as e:
            raise ValueError(f"{key} must be an integer, got {value!r}") from e
    elif key in _BOOL_KEYS:
        setattr(cfg, key, _to_bool(value))
    else:
        setattr(cfg, key, value)
    save_config(cfg, path)
    return cfg


def get_value(key: str, path: Path = CONFIG_PATH) -> Any:
    if key not in VALID_KEYS:
        raise KeyError(f"unknown config key: {key}")
    return getattr(load_config(path), key)


def resolve_style(cli_value: Optional[str], cfg: StatusbarConfig) -> str:
    if cli_value:
        return cli_value
    env = os.environ.get("CLAUDE_STATUSBAR_STYLE")
    if env:
        return env
    return cfg.style


def resolve_theme(cli_value: Optional[str], cfg: StatusbarConfig) -> str:
    if cli_value:
        return cli_value
    env = os.environ.get("CLAUDE_STATUSBAR_THEME")
    if env:
        return env
    return cfg.theme
