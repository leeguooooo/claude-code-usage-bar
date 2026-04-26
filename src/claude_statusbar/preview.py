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
from .themes import BUILTIN_THEMES, get_theme

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
    return dict(
        msgs_pct=int(round(fh.get("used_percentage", 0))),
        weekly_pct=int(round(sd.get("used_percentage", 0))),
        reset_5h=_fmt_reset(fh.get("resets_at")),
        reset_7d=_fmt_reset(sd.get("resets_at")),
        model=name,
    )


def _demo_data() -> dict:
    return dict(
        msgs_pct=42, weekly_pct=18,
        reset_5h="3h28m", reset_7d="5d12h",
        model="Opus 4.7(45.0k/1.0M)",
    )


def run(use_color: bool = True) -> int:
    real = _real_data()
    data = real or _demo_data()
    src_label = "用你当前的真实数据" if real else "演示数据（找不到 last_stdin.json）"

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
    # Classic predates the theme system and ignores Theme entirely, so showing
    # 7 rows of identical output is just visual noise.
    THEME_AGNOSTIC = {"classic"}

    for style_name in RENDERERS:
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
                lang_body="", pet_body="", bypass=False,
                use_color=use_color,
                warning_threshold=30.0, critical_threshold=70.0,
            )
            print(f"  {DIM}[theme-agnostic]{R} {line}")
            continue
        for theme in BUILTIN_THEMES:
            line = render(
                style_name, theme=theme,
                msgs_pct=data["msgs_pct"], weekly_pct=data["weekly_pct"],
                reset_5h=data["reset_5h"], reset_7d=data["reset_7d"],
                model=data["model"],
                lang_body="", pet_body="", bypass=False,
                use_color=use_color,
                warning_threshold=30.0, critical_threshold=70.0,
            )
            print(f"  {DIM}[{theme.name:<9}]{R} {line}")
    print()

    print(f"  {DIM}切换：cs config set style <name> · cs config set theme <name>{R}")
    print()
    return 0
