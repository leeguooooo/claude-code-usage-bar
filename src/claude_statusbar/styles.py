"""Status-line layout renderers (style = layout, theme = palette).

Each renderer takes the same set of fields as ``progress.format_status_line``
plus a Theme, and returns the final ANSI string.

Adding a new style:
    1. Define ``render_<name>(...) -> str``
    2. Register it in ``RENDERERS``.
"""

from typing import Optional

from .themes import Theme, get_theme

RESET = "\033[0m"
BOLD  = "\033[1m"
ITAL  = "\033[3m"

def _fg(rgb): return f"\033[38;2;{rgb[0]};{rgb[1]};{rgb[2]}m"
def _bg(rgb): return f"\033[48;2;{rgb[0]};{rgb[1]};{rgb[2]}m"

# strip ANSI when use_color is False
import re as _re
_ANSI_RE = _re.compile(r"\033\[[0-9;]*m")
def _strip(s: str) -> str: return _ANSI_RE.sub("", s)


def _severity_color(theme: Theme, pct: Optional[float],
                     warning: float, critical: float) -> tuple:
    if pct is None:
        return theme.mute
    if pct >= critical: return theme.s_hot
    if pct >= warning:  return theme.s_warn
    return theme.s_ok


# ---------------------------------------------------------------------------
# Style: capsule
# ---------------------------------------------------------------------------
def render_capsule(
    *, msgs_pct, weekly_pct, reset_5h, reset_7d, model,
    lang_text="", pet_text="", bypass=False,
    use_color=True, theme: Optional[Theme]=None,
    warning_threshold=30.0, critical_threshold=70.0,
    density: str = "regular",
    show_weekly: bool = True,
) -> str:
    theme = theme or get_theme("graphite")
    INK    = _fg(theme.pill_ink)
    EDGE   = _fg(theme.edge)
    MUTE   = _fg(theme.mute)

    pad = {"compact": "", "regular": " ", "cozy": "  "}.get(density, " ")

    def pill(bg_rgb, body):
        return f"{_bg(bg_rgb)}{INK}{pad}{body}{pad}{RESET}"

    def sev_dot(p):
        if p is None:
            return ""
        col = _severity_color(theme, p, warning_threshold, critical_threshold)
        return f" {_fg(col)}●{RESET}"

    def pct_text(p):
        return "--%" if p is None else f"{int(round(p))}%"

    spacer = f"{EDGE} ╱{RESET} "

    parts = []

    five_body = (
        f"{BOLD}◷ 5H{RESET}{INK}{_bg(theme.pill_5h)} {pct_text(msgs_pct)} "
        f"· {reset_5h}{sev_dot(msgs_pct)}{INK}{_bg(theme.pill_5h)}"
    )
    parts.append(pill(theme.pill_5h, five_body))

    if show_weekly:
        week_body = (
            f"{BOLD}☷ 7D{RESET}{INK}{_bg(theme.pill_7d)} {pct_text(weekly_pct)} "
            f"· {reset_7d or '--'}{sev_dot(weekly_pct)}{INK}{_bg(theme.pill_7d)}"
        )
        parts.append(pill(theme.pill_7d, week_body))

    parts.append(pill(theme.pill_model, f"{BOLD}◆{RESET}{INK}{_bg(theme.pill_model)} {model}"))

    if lang_text:
        # lang_text may already carry ANSI — strip and re-render in pill colors
        plain = _strip(lang_text).strip()
        # drop the leading 📚 if present (we re-add inside the pill)
        plain = plain.lstrip("📚 ").strip()
        parts.append(pill(theme.pill_lang, f"📚 {plain}"))

    line = spacer.join(parts)

    if bypass:
        line += f"  {_fg(theme.s_hot)}{BOLD}⚠ BYPASS{RESET}"

    if pet_text:
        plain = _strip(pet_text).strip()
        line += f"  {MUTE}{plain}{RESET}"

    if not use_color:
        return _strip(line)
    return line


# ---------------------------------------------------------------------------
# Style: hairline
# ---------------------------------------------------------------------------
def render_hairline(
    *, msgs_pct, weekly_pct, reset_5h, reset_7d, model,
    lang_text="", pet_text="", bypass=False,
    use_color=True, theme: Optional[Theme]=None,
    warning_threshold=30.0, critical_threshold=70.0,
    density: str = "regular",
    show_weekly: bool = True,
) -> str:
    theme = theme or get_theme("graphite")
    INK  = _fg(theme.ink)
    MUTE = _fg(theme.mute)
    EDGE = _fg(theme.edge)

    def mini3(p):
        if p is None:
            return f"{MUTE}···{RESET}"
        cells = []
        for i in range(3):
            slot = (i + 1) * (100 / 3)
            if   p >= slot:                   cells.append("█")
            elif p >= slot - (100 / 3) * 0.66: cells.append("▆")
            elif p >= slot - (100 / 3):       cells.append("▃")
            else:                             cells.append("▁")
        col = _severity_color(theme, p, warning_threshold, critical_threshold)
        return f"{_fg(col)}{''.join(cells)}{RESET}"

    def pct_text(p):
        return "--%" if p is None else f"{int(round(p)):>2}%"

    sep_pad = {"compact": "", "regular": " ", "cozy": "  "}.get(density, " ")
    sep = f"{sep_pad}{EDGE}┊{RESET}{sep_pad}"
    parts = []

    parts.append(
        f"{MUTE}› 5h{RESET} {mini3(msgs_pct)} {INK}{pct_text(msgs_pct)}{RESET} "
        f"{MUTE}↺ {reset_5h}{RESET}"
    )
    if show_weekly:
        parts.append(
            f"{MUTE}› 7d{RESET} {mini3(weekly_pct)} {INK}{pct_text(weekly_pct)}{RESET} "
            f"{MUTE}↺ {reset_7d or '--'}{RESET}"
        )
    parts.append(f"{MUTE}›{RESET} {INK}{model}{RESET}")

    if lang_text:
        plain = _strip(lang_text).strip()
        parts.append(f"{MUTE}{plain}{RESET}")

    if bypass:
        parts.append(f"{_fg(theme.s_hot)}{BOLD}⚠ BYPASS{RESET}")

    if pet_text:
        plain = _strip(pet_text).strip()
        parts.append(f"{MUTE}{plain}{RESET}")

    line = sep.join(parts)
    if not use_color:
        return _strip(line)
    return line


# ---------------------------------------------------------------------------
# Style: classic — wraps the existing format_status_line for backward compat
# ---------------------------------------------------------------------------
def render_classic(
    *, msgs_pct, weekly_pct, reset_5h, reset_7d, model,
    lang_text="", pet_text="", bypass=False,
    use_color=True, theme: Optional[Theme]=None,
    warning_threshold=30.0, critical_threshold=70.0,
    countdown_emoji: str = "",
) -> str:
    from .progress import format_status_line
    return format_status_line(
        msgs_pct=msgs_pct, tkns_pct=None,
        reset_time=reset_5h, model=model,
        weekly_pct=weekly_pct, reset_time_7d=reset_7d or "",
        bypass=bypass, use_color=use_color,
        pet_text=pet_text, countdown_emoji=countdown_emoji,
        warning_threshold=warning_threshold,
        critical_threshold=critical_threshold,
        lang_text=lang_text,
    )


RENDERERS = {
    "classic":  render_classic,
    "capsule":  render_capsule,
    "hairline": render_hairline,
}


def render(style: str, **kwargs) -> str:
    """Render with the named style, falling back to classic for unknown names."""
    fn = RENDERERS.get(style, render_classic)
    return fn(**kwargs)


def list_styles() -> list[str]:
    return list(RENDERERS.keys())
