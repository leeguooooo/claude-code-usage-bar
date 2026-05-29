"""`cs preview` — render every style × theme combination at once.

Pulls real numbers from ~/.cache/claude-statusbar/last_stdin.json when
available, so what you see is exactly what your status line would look
like after switching. Falls back to plausible demo data otherwise.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .styles import RENDERERS, render
from .themes import BUILTIN_THEMES

CACHED_STDIN = Path.home() / ".cache" / "claude-statusbar" / "last_stdin.json"


def _fmt_num(n: float) -> str:
    if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
    if n >= 1_000:     return f"{n/1_000:.1f}k"
    return f"{n:.0f}"


def _fmt_reset(ts: Optional[int]) -> str:
    if not ts:
        return "--"
    diff = datetime.fromtimestamp(ts, tz=timezone.utc) - datetime.now(timezone.utc)
    s = max(0, int(diff.total_seconds()))
    d, s = divmod(s, 86400); h, s = divmod(s, 3600); m = s // 60
    if d > 0: return f"{d}d{h:02d}h"
    if h > 0: return f"{h}h{m:02d}m"
    return f"{m}m"


def _real_data() -> Optional[dict]:
    try:
        raw = json.loads(CACHED_STDIN.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    rl = raw.get("rate_limits") or {}
    fh = rl.get("five_hour", {}) or {}
    sd = rl.get("seven_day", {}) or {}
    cw = raw.get("context_window") or {}
    mdl = raw.get("model") or {}
    name = re.sub(
        r"\s*\([^)]*context[^)]*\)", "",
        mdl.get("display_name") or mdl.get("id", "Unknown"),
    )
    used = cw.get("total_input_tokens", 0) + cw.get("total_output_tokens", 0)
    size = cw.get("context_window_size", 0)
    if size > 0:
        name = f"{name}({_fmt_num(used)}/{_fmt_num(size)})"

    # Optional segments — compute the same way core.main does so preview
    # actually shows what the live status line shows.
    from .core import get_cache_age_text
    cache_age_text = get_cache_age_text()  # auto-detect TTL, same as core.main

    cost_text = ""
    sc = raw.get("session_cost_usd") or (raw.get("cost") or {}).get("total_cost_usd")
    if isinstance(sc, (int, float)) and sc >= 0:
        cost_text = f"{sc:.2f}"

    return dict(
        msgs_pct=int(round(fh.get("used_percentage", 0))),
        weekly_pct=int(round(sd.get("used_percentage", 0))),
        reset_5h=_fmt_reset(fh.get("resets_at")),
        reset_7d=_fmt_reset(sd.get("resets_at")),
        model=name,
        cache_age_text=cache_age_text,
        cost_text=cost_text,
    )


def _demo_data() -> dict:
    return dict(
        msgs_pct=42, weekly_pct=18,
        reset_5h="3h28m", reset_7d="5d12h",
        model="Opus 4.7(45.0k/1.0M)",
        cache_age_text="3m24s",  # warm — demo what countdown looks like
        cost_text="2.18",
    )


def run(use_color: bool = True, theme_filter: Optional[str] = None,
        style_filter: Optional[str] = None) -> int:
    """Render style × theme matrix.

    `theme_filter` / `style_filter` (optional) limit output to one row.
    Useful when the user is comparing a specific combo: `cs preview --theme nord`
    shows nord across all 3 styles; `cs preview --style hairline --theme dracula`
    shows just that one combo.
    """
    real = _real_data()
    data = real or _demo_data()
    src_label = "用你当前的真实数据" if real else "演示数据(找不到 last_stdin.json)"

    GOLD = "\033[38;2;212;175;55m\033[1m"
    DIM  = "\033[38;2;110;110;115m"
    OK   = "\033[38;2;120;200;192m"
    R    = "\033[0m"

    if not use_color:
        GOLD = DIM = OK = R = ""

    print()
    print(f"  {OK}● 数据源{R}：{src_label}")
    print(f"  {DIM}5h={data['msgs_pct']}% · 7d={data['weekly_pct']}% · {data['model']}{R}")

    style_titles = {
        "classic":  "01 · CLASSIC（原版）",
        "capsule":  "02 · CAPSULE（胶囊）",
        "hairline": "03 · HAIRLINE（极简线条）",
    }
    # All three styles are theme-aware now (per-segment color management).
    # Keeping THEME_AGNOSTIC as an empty set so the per-theme loop picks up
    # every style; future theme-agnostic styles can be added here.
    THEME_AGNOSTIC: set[str] = set()

    style_names = list(RENDERERS)
    if style_filter:
        if style_filter not in style_names:
            print(f"  {DIM}unknown style {style_filter!r}; valid: {', '.join(style_names)}{R}")
            return 2
        style_names = [style_filter]

    themes = list(BUILTIN_THEMES)
    if theme_filter:
        themes = [t for t in themes if t.name == theme_filter]
        if not themes:
            valid = ", ".join(t.name for t in BUILTIN_THEMES)
            print(f"  {DIM}unknown theme {theme_filter!r}; valid: {valid}{R}")
            return 2

    for style_name in style_names:
        title = style_titles.get(style_name, style_name)
        print()
        print(f"  {GOLD}{title}{R}")
        print(f"  {DIM}{'─' * 78}{R}")
        if style_name in THEME_AGNOSTIC:
            line = render(
                style_name, theme=BUILTIN_THEMES[0],
                msgs_pct=data["msgs_pct"], weekly_pct=data["weekly_pct"],
                reset_5h=data["reset_5h"], reset_7d=data["reset_7d"],
                model=data["model"],
                lang_body="",
                cost_text=data.get("cost_text", ""),
                cache_age_text=data.get("cache_age_text", ""),
                bypass=False,
                use_color=use_color,
                warning_threshold=30.0, critical_threshold=70.0,
            )
            print(f"  {DIM}[theme-agnostic]{R} {line}")
            continue
        for theme in themes:
            line = render(
                style_name, theme=theme,
                msgs_pct=data["msgs_pct"], weekly_pct=data["weekly_pct"],
                reset_5h=data["reset_5h"], reset_7d=data["reset_7d"],
                model=data["model"],
                lang_body="",
                cost_text=data.get("cost_text", ""),
                cache_age_text=data.get("cache_age_text", ""),
                bypass=False,
                use_color=use_color,
                warning_threshold=30.0, critical_threshold=70.0,
            )
            print(f"  {DIM}[{theme.name:<9}]{R} {line}")
    print()

    print(f"  {DIM}切换：cs config set style <name> · cs config set theme <name>{R}")
    print()
    return 0
