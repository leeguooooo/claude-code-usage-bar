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
DEFAULT_CACHE_TTL_SECONDS = 300  # 5min — Anthropic's base prompt cache TTL.
DEFAULT_API_MODE = "auto"  # auto-detect relay/Bedrock/Vertex | on (force) | off (force official)
# DEPRECATED: the cache countdown now auto-detects the real TTL (5m vs 1h)
# from the transcript's message.usage.cache_creation buckets, which reflect
# subscription/API-key auth, ENABLE_PROMPT_CACHING_1H, FORCE_PROMPT_CACHING_5M
# and the over-quota downgrade — see core.get_cache_age_text. The
# cache_ttl_seconds field below is kept only so existing configs and
# `cs config set cache_ttl_seconds …` don't error; it no longer affects render.


@dataclass
class StatusbarConfig:
    style: str = DEFAULT_STYLE
    theme: str = DEFAULT_THEME
    density: str = DEFAULT_DENSITY
    auto_compact_width: int = DEFAULT_AUTO_COMPACT_WIDTH
    show_weekly: bool = True
    show_language: bool = True
    show_cost: bool = False
    # Relay account balance (no-quota mode only). Auto: shown when the relay
    # exposes an OpenAI-compatible billing endpoint, silently hidden otherwise.
    show_balance: bool = True
    # Render the balance as a fuel-gauge battery (fill = remaining %) instead of
    # plain `bal $X`. Falls back to text when the relay reports no usable limit.
    balance_bar: bool = True
    show_cache_age: bool = True
    show_project_branch: bool = True
    # Live-activity / session-stats segments. show_todos (activity line) and
    # show_lines (+added -removed on the identity line) default on; the rest are
    # opt-in so the line isn't crowded for users who didn't ask.
    show_todos: bool = True
    show_tools: bool = False
    show_tool_rollup: bool = False
    show_agents: bool = False
    # Egress-IP risk chip on the identity line (proxycheck.io, 30-min cadence,
    # detached prober — see ip_risk.py). Opt-in: it talks to a third party.
    show_ip_risk: bool = False
    show_duration: bool = False
    show_lines: bool = True
    show_ahead_behind: bool = False
    # A faint `· vX.Y.Z` at the very end of the identity line (dimmest grey).
    show_version: bool = True
    # A dedicated `⚙ effort:… · think:… · fast:… · style:…` session-mode line.
    show_mode: bool = True
    # When effort is top-tier (xhigh/max/ultracode), flow a pink→purple gradient
    # across the whole mode line (steps ~1 char/s — statusLine can't animate
    # smoothly). Default on.
    mode_gradient: bool = True
    # Experimental: a lightened cell sweeping the battery bar's filled portion,
    # advancing one cell per render. Capped at the statusLine's ~1Hz refresh,
    # so it's a slow step, not smooth. Default off; classic style only.
    bar_shimmer: bool = False
    # When on, shows the at-risk `⚠<eta>` warning chip when projected to hit the
    # cap before reset.
    show_forecast: bool = True
    # When on, shows each window's projected end-of-window usage (`→NN%`) after
    # its reset timer. Separate from the warning chip above.
    show_projection: bool = True
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS  # deprecated; auto-detected now
    # No-quota mode: drop the 5h/7d quota bars and promote context when official
    # quota is unavailable (third-party relay via ANTHROPIC_BASE_URL, Bedrock,
    # Vertex). "auto" detects from the environment; "on"/"off" force it.
    api_mode: str = DEFAULT_API_MODE
    warning_threshold: Optional[float] = None
    critical_threshold: Optional[float] = None
    # Per-severity color overrides — hex like "#4ec85b". None means "use the
    # active theme's value". Layer on top of the resolved Theme, never mutate
    # the theme itself. Set via `cs config set color_ok "#4ec85b"`; clear by
    # setting to empty string.
    color_ok: Optional[str] = None
    color_warn: Optional[str] = None
    color_hot: Optional[str] = None


def _to_bool(v):
    if isinstance(v, bool): return v
    s = str(v).strip().lower()
    return s in ("1", "true", "yes", "on", "y", "t")


def load_config(path: Optional[Path] = None) -> StatusbarConfig:
    path = CONFIG_PATH if path is None else path
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
        show_weekly=_to_bool(raw.get("show_weekly", True)),
        show_language=_to_bool(raw.get("show_language", True)),
        show_cost=_to_bool(raw.get("show_cost", False)),
        show_balance=_to_bool(raw.get("show_balance", True)),
        balance_bar=_to_bool(raw.get("balance_bar", True)),
        show_cache_age=_to_bool(raw.get("show_cache_age", True)),
        show_project_branch=_to_bool(raw.get("show_project_branch", True)),
        show_todos=_to_bool(raw.get("show_todos", True)),
        show_tools=_to_bool(raw.get("show_tools", False)),
        show_tool_rollup=_to_bool(raw.get("show_tool_rollup", False)),
        show_agents=_to_bool(raw.get("show_agents", False)),
        show_ip_risk=_to_bool(raw.get("show_ip_risk", False)),
        show_duration=_to_bool(raw.get("show_duration", False)),
        show_lines=_to_bool(raw.get("show_lines", True)),
        show_ahead_behind=_to_bool(raw.get("show_ahead_behind", False)),
        show_version=_to_bool(raw.get("show_version", True)),
        show_mode=_to_bool(raw.get("show_mode", True)),
        mode_gradient=_to_bool(raw.get("mode_gradient", True)),
        bar_shimmer=_to_bool(raw.get("bar_shimmer", False)),
        show_forecast=_to_bool(raw.get("show_forecast", True)),
        show_projection=_to_bool(raw.get("show_projection", True)),
        cache_ttl_seconds=int(raw.get("cache_ttl_seconds", DEFAULT_CACHE_TTL_SECONDS) or DEFAULT_CACHE_TTL_SECONDS),
        api_mode=str(raw.get("api_mode", DEFAULT_API_MODE)),
        warning_threshold=raw.get("warning_threshold"),
        critical_threshold=raw.get("critical_threshold"),
        color_ok=raw.get("color_ok") or None,
        color_warn=raw.get("color_warn") or None,
        color_hot=raw.get("color_hot") or None,
    )


def save_config(cfg: StatusbarConfig, path: Optional[Path] = None) -> None:
    """Persist config atomically — Ctrl+C mid-write must not corrupt JSON."""
    path = CONFIG_PATH if path is None else path
    from .cache import atomic_write_text
    atomic_write_text(path, json.dumps(asdict(cfg), indent=2, ensure_ascii=False) + "\n")


VALID_KEYS = {
    "style", "theme", "density", "auto_compact_width",
    "show_weekly", "show_language", "show_cost", "show_balance", "balance_bar",
    "show_cache_age",
    "show_project_branch",
    "show_todos", "show_tools", "show_tool_rollup", "show_agents",
    "show_ip_risk",
    "show_duration", "show_lines", "show_ahead_behind", "show_version",
    "bar_shimmer", "show_forecast", "show_projection",
    "show_mode", "mode_gradient",
    "cache_ttl_seconds", "api_mode",
    "warning_threshold", "critical_threshold",
    "color_ok", "color_warn", "color_hot",
}
_VALID_API_MODE = {"auto", "on", "off"}
_BOOL_KEYS = {"show_weekly", "show_language", "show_cost", "show_balance",
              "balance_bar",
              "show_cache_age",
              "show_project_branch",
              "show_todos", "show_tools", "show_tool_rollup", "show_agents",
              "show_ip_risk",
              "show_duration", "show_lines", "show_ahead_behind", "show_version",
              "bar_shimmer", "show_forecast", "show_projection",
              "show_mode", "mode_gradient"}
_FLOAT_KEYS = {"warning_threshold", "critical_threshold"}
_INT_KEYS = {"auto_compact_width", "cache_ttl_seconds"}
_COLOR_KEYS = {"color_ok", "color_warn", "color_hot"}
_VALID_DENSITY = {"compact", "regular", "cozy"}


def set_value(key: str, value: str, path: Optional[Path] = None) -> StatusbarConfig:
    path = CONFIG_PATH if path is None else path
    if key not in VALID_KEYS:
        raise KeyError(f"unknown config key: {key} (valid: {sorted(VALID_KEYS)})")
    cfg = load_config(path)
    if key in _FLOAT_KEYS:
        try:
            new_val = float(value)
        except ValueError as e:
            raise ValueError(f"{key} must be a number, got {value!r}") from e
        # Cross-field check: warning < critical must hold or every render crashes.
        # Use the resulting pair (existing other field + new value) to validate.
        from .progress import normalize_thresholds
        if key == "warning_threshold":
            other = cfg.critical_threshold
        else:
            other = cfg.warning_threshold
        try:
            if key == "warning_threshold":
                normalize_thresholds(new_val, other)
            else:
                normalize_thresholds(other, new_val)
        except ValueError as e:
            raise ValueError(
                f"refusing to save: {key}={new_val} would make the pair invalid "
                f"(warning_threshold={cfg.warning_threshold}, "
                f"critical_threshold={cfg.critical_threshold}). "
                f"Set both keys or use --warning-threshold / --critical-threshold "
                f"together."
            ) from e
        setattr(cfg, key, new_val)
        save_config(cfg, path)
        return cfg
    if key in _COLOR_KEYS:
        # Empty string clears the override (falls back to theme default).
        if value == "":
            setattr(cfg, key, None)
        else:
            from .themes import parse_hex_color
            r, g, b = parse_hex_color(value)
            setattr(cfg, key, f"#{r:02x}{g:02x}{b:02x}")
        save_config(cfg, path)
        return cfg
    if key in _INT_KEYS:
        try:
            setattr(cfg, key, int(value))
        except ValueError as e:
            raise ValueError(f"{key} must be an integer, got {value!r}") from e
    elif key in _BOOL_KEYS:
        setattr(cfg, key, _to_bool(value))
    elif key == "density":
        if value not in _VALID_DENSITY:
            raise ValueError(f"density must be one of {sorted(_VALID_DENSITY)}, got {value!r}")
        setattr(cfg, key, value)
    elif key == "api_mode":
        if value not in _VALID_API_MODE:
            raise ValueError(f"api_mode must be one of {sorted(_VALID_API_MODE)}, got {value!r}")
        setattr(cfg, key, value)
    elif key == "style":
        # Lazy import to avoid a config↔styles cycle at module load.
        from .styles import list_styles
        valid = set(list_styles())
        if value not in valid:
            raise ValueError(f"style must be one of {sorted(valid)}, got {value!r}")
        setattr(cfg, key, value)
    elif key == "theme":
        from .themes import list_themes
        valid = {t.name for t in list_themes()}
        if value not in valid:
            raise ValueError(f"theme must be one of {sorted(valid)}, got {value!r}")
        setattr(cfg, key, value)
    else:
        setattr(cfg, key, value)
    save_config(cfg, path)
    return cfg


def get_value(key: str, path: Optional[Path] = None) -> Any:
    path = CONFIG_PATH if path is None else path
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


def resolve_api_mode(cfg: StatusbarConfig, env: Optional[dict] = None) -> str:
    """Effective api_mode: CS_API_MODE env wins over the saved config, so a relay
    user can force the layout per-shell without editing config. Unknown values
    fall through to detection (is_no_quota_mode treats non on/off as auto).

    `env` defaults to os.environ; the render path passes the per-session env
    (stamped by render_thin) so the shared daemon reads the session's CS_API_MODE
    rather than its own frozen start-time value."""
    source = os.environ if env is None else env
    val = source.get("CS_API_MODE")
    if val:
        return val.strip().lower()
    return cfg.api_mode


def resolve_theme(cli_value: Optional[str], cfg: StatusbarConfig) -> str:
    if cli_value:
        return cli_value
    env = os.environ.get("CLAUDE_STATUSBAR_THEME")
    if env:
        return env
    return cfg.theme
