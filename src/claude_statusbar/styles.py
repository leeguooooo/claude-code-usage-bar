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
FAINT = "\033[2m"   # dim/faint attribute — makes a grey recede even further

# Installed version, resolved once and cached. importlib.metadata is ~20ms and
# banned on the per-render import graph, but a lazy call here (only when the
# version segment is on) is fine: it's not an import-time edge, and the daemon
# pays it once per process. Empty string if it can't be determined.
_VERSION_CACHE = None
def _statusbar_version() -> str:
    global _VERSION_CACHE
    if _VERSION_CACHE is None:
        try:
            import importlib.metadata as _m
            _VERSION_CACHE = _m.version("claude-statusbar")
        except Exception:
            _VERSION_CACHE = ""
    return _VERSION_CACHE


def _version_gt(a: str, b: str) -> bool:
    """True if dotted version `a` is newer than `b`. Fail-safe (bad parts → 0)."""
    def parts(v):
        out = []
        for x in str(v).split("."):
            try:
                out.append(int(x))
            except ValueError:
                out.append(0)
        return out
    pa, pb = parts(a), parts(b)
    n = max(len(pa), len(pb))
    pa += [0] * (n - len(pa))
    pb += [0] * (n - len(pb))
    return pa > pb


def _update_hint(path=None) -> str:
    """The newer version string if the cached PyPI check says one is available
    (and the check is recent), else ''. Cheap file read — no network, no
    importlib on the hot path. Written by updater.get_latest_version."""
    try:
        import json as _json
        import time as _t
        from pathlib import Path as _Path
        p = _Path(path) if path is not None else (
            _Path.home() / ".cache" / "claude-statusbar" / "latest_version.json")
        data = _json.loads(p.read_text(encoding="utf-8"))
        latest = str(data.get("version", ""))
        checked_at = float(data.get("checked_at", 0))
        if not latest or _t.time() - checked_at > 7 * 86400:  # stale → no arrow
            return ""
        return latest if _version_gt(latest, _statusbar_version()) else ""
    except Exception:
        return ""

def _fg(rgb): return f"\033[38;2;{rgb[0]};{rgb[1]};{rgb[2]}m"
def _bg(rgb): return f"\033[48;2;{rgb[0]};{rgb[1]};{rgb[2]}m"

# strip ANSI when use_color is False
import re as _re
_ANSI_RE = _re.compile(r"\033\[[0-9;]*m")
def _strip(s: str) -> str: return _ANSI_RE.sub("", s)

# Density → padding string, shared by all renderers that support it.
DENSITY_PAD = {"compact": "", "regular": " ", "cozy": "  "}


def _severity_color(theme: Theme, pct: Optional[float],
                     warning: float, critical: float) -> tuple:
    if pct is None:
        return theme.mute
    if pct >= critical: return theme.s_hot
    if pct >= warning:  return theme.s_warn
    return theme.s_ok


def _cache_severity(theme: Theme, cache_text: str) -> tuple:
    """Map a countdown cache string to a severity color.

    "COLD"            → s_hot   (red, expired)
    "<1m" remaining   → s_warn  (yellow, ~1min left)
    otherwise         → s_ok    (green, comfortable)

    The "<1m" detection works because the countdown formatter only emits
    sub-minute remainders as bare "Ys" (no 'm', no 'h'). Anything with a
    minute or hour glyph is in the comfortable zone.
    """
    if cache_text == "COLD":
        return theme.s_hot
    # Comfortable: contains 'm' (minutes) or 'h' (hours).
    if "m" in cache_text or "h" in cache_text:
        return theme.s_ok
    return theme.s_warn


# ---------------------------------------------------------------------------
# Style: capsule
# ---------------------------------------------------------------------------
def render_capsule(
    *, msgs_pct, weekly_pct, reset_5h, reset_7d, model,
    lang_body="", cost_text="", cache_age_text="", bypass=False,
    use_color=True, theme: Optional[Theme]=None,
    warning_threshold=30.0, critical_threshold=70.0,
    density: str = "regular",
    show_weekly: bool = True,
    ctx_pct: Optional[float] = None,
    **_ignored,
) -> str:
    theme = theme or get_theme("graphite")
    INK    = _fg(theme.pill_ink)
    EDGE   = _fg(theme.edge)
    MUTE   = _fg(theme.mute)

    pad = DENSITY_PAD.get(density, " ")

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

    model_body = f"{BOLD}◆{RESET}{INK}{_bg(theme.pill_model)} {model}{sev_dot(ctx_pct)}{INK}{_bg(theme.pill_model)}"
    parts.append(pill(theme.pill_model, model_body))

    if cost_text:
        parts.append(pill(theme.pill_cost, f"$ {cost_text}"))

    if lang_body:
        parts.append(pill(theme.pill_lang, f"📚 {lang_body}"))

    if cache_age_text:
        bg = _cache_severity(theme, cache_age_text)
        parts.append(pill(bg, f"cache {cache_age_text}"))

    line = spacer.join(parts)

    if bypass:
        line += f"  {_fg(theme.s_hot)}{BOLD}⚠ BYPASS{RESET}"

    if not use_color:
        return _strip(line)
    return line


# ---------------------------------------------------------------------------
# Style: hairline
# ---------------------------------------------------------------------------
def render_hairline(
    *, msgs_pct, weekly_pct, reset_5h, reset_7d, model,
    lang_body="", cost_text="", cache_age_text="", bypass=False,
    use_color=True, theme: Optional[Theme]=None,
    warning_threshold=30.0, critical_threshold=70.0,
    density: str = "regular",
    show_weekly: bool = True,
    ctx_pct: Optional[float] = None,
    **_ignored,
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

    sep_pad = DENSITY_PAD.get(density, " ")
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
    # Model line — colored by ctx_pct severity, neutral ink when absent
    if ctx_pct is None:
        model_color = INK
    else:
        col = _severity_color(theme, ctx_pct, warning_threshold, critical_threshold)
        model_color = _fg(col)
    parts.append(f"{MUTE}›{RESET} {model_color}{model}{RESET}")

    if cost_text:
        parts.append(f"{MUTE}$ {INK}{cost_text}{RESET}")

    if lang_body:
        parts.append(f"{MUTE}{lang_body}{RESET}")

    if cache_age_text:
        col = _fg(_cache_severity(theme, cache_age_text))
        parts.append(f"{col}cache {cache_age_text}{RESET}")

    if bypass:
        parts.append(f"{_fg(theme.s_hot)}{BOLD}⚠ BYPASS{RESET}")

    line = sep.join(parts)
    if not use_color:
        return _strip(line)
    return line


# ---------------------------------------------------------------------------
# Style: classic — wraps the existing format_status_line for backward compat
# ---------------------------------------------------------------------------
def render_classic(
    *, msgs_pct, weekly_pct, reset_5h, reset_7d, model,
    lang_body="", cost_text="", cache_age_text="", bypass=False,
    use_color=True, theme: Optional[Theme]=None,
    warning_threshold=30.0, critical_threshold=70.0,
    countdown_emoji: str = "",
    ctx_pct: Optional[float] = None,
    shimmer_phase=None,
    projection_5h: str = "",
    projection_7d: str = "",
    forecast_5h: str = "",
    forecast_7d: str = "",
    **_ignored,
) -> str:
    from .progress import format_status_line, _fg, colorize, RESET
    theme = theme or get_theme("graphite")
    lang_text = (
        colorize(f"📚 {lang_body}", _fg(theme.s_ok), use_color)
        if lang_body else ""
    )
    result = format_status_line(
        msgs_pct=msgs_pct, tkns_pct=None,
        reset_time=reset_5h, model=model,
        weekly_pct=weekly_pct, reset_time_7d=reset_7d or "",
        ctx_pct=ctx_pct,
        bypass=bypass, use_color=use_color,
        countdown_emoji=countdown_emoji,
        warning_threshold=warning_threshold,
        critical_threshold=critical_threshold,
        lang_text=lang_text,
        cost_text=cost_text,
        theme=theme,
        shimmer_phase=shimmer_phase,
        projection_5h=projection_5h,
        projection_7d=projection_7d,
        forecast_5h=forecast_5h,
        forecast_7d=forecast_7d,
    )
    if cache_age_text:
        # Three-level severity: COLD red, <1m yellow, otherwise green.
        if cache_age_text == "COLD":
            col = _fg(theme.s_hot)
        elif "m" in cache_age_text or "h" in cache_age_text:
            col = _fg(theme.s_ok)
        else:
            col = _fg(theme.s_warn)
        mute = _fg(theme.mute)
        reset = RESET if use_color else ""  # don't leak a bare RESET in no-color mode
        result += f"{reset}{colorize(' | ', mute, use_color)}{colorize(f'cache {cache_age_text}', col, use_color)}"
    return result


def _ahead_behind_glyphs(ahead, behind) -> str:
    """`↑2↓1` / `↑3` / `↓1` / "" — only the nonzero directions."""
    out = ""
    if ahead:
        out += f"↑{ahead}"
    if behind:
        out += f"↓{behind}"
    return out


def _stats_segment(duration_text: str, lines_text: str, *, theme: Theme,
                   use_color: bool) -> str:
    """The ` · ⏱ <dur> · +added -removed` tail appended to the identity line.

    Returns "" when neither is present. Diff colors: +added green, -removed red.
    """
    if not (duration_text or lines_text):
        return ""
    # Lines (productivity) first, then the weaker duration signal.
    if not use_color:
        parts = []
        if lines_text:
            parts.append(lines_text)
        if duration_text:
            parts.append(f"⏱ {duration_text}")
        return " · " + " · ".join(parts)
    MUTE = _fg(theme.mute)
    INK  = _fg(theme.ink)
    OK   = _fg(theme.s_ok)
    HOT  = _fg(theme.s_hot)
    segs = []
    if lines_text:
        toks = []
        for tok in lines_text.split():
            c = OK if tok.startswith("+") else HOT if tok.startswith("-") else MUTE
            toks.append(f"{c}{tok}{RESET}")
        segs.append(" ".join(toks))
    if duration_text:
        segs.append(f"{MUTE}⏱{RESET} {INK}{duration_text}{RESET}")
    sep = f" {MUTE}·{RESET} "
    return f" {MUTE}·{RESET} " + sep.join(segs)


def render_identity_line(info, *, theme: Theme, dirty,
                         ahead=None, behind=None,
                         duration_text: str = "", lines_text: str = "",
                         version_text: str = "", update_text: str = "",
                         use_color: bool = True) -> str:
    """Render the 2nd line: `⤷ <project> ⎇ <branch>●↑2↓1 · ⏱ <dur> · +/-lines`.

    `dirty` is True / False / None — None means "unknown" (cache miss);
    in that case we omit the dot rather than asserting clean. `ahead`/`behind`
    are commits relative to upstream (None = unknown/no upstream, 0 = in sync);
    arrows render only for nonzero directions and only inside a git repo.
    `duration_text`/`lines_text` are the session stats, shown here (next to the
    project) rather than on the live-activity line. When the checkout is a
    linked git worktree (`info.is_worktree`), a bare ``[worktree]`` marker is
    appended after the branch — a boolean signal only; the branch already
    says which worktree it is, so the name isn't repeated.
    """
    ab = _ahead_behind_glyphs(ahead, behind) if info.in_git else ""
    stats = _stats_segment(duration_text, lines_text, theme=theme,
                           use_color=use_color)

    if not use_color:
        head = f"⤷ {info.project_name}"
        if not info.in_git:
            tail = " (no git)"
        else:
            branch = info.branch or "?"
            dot = "●" if dirty else ""
            tail = f" ⎇ {branch}{dot}"
            if ab:
                tail += f" {ab}"
        if info.is_worktree:
            tail += " [worktree]"
        ver = f" · v{version_text}" if version_text else ""
        if version_text and update_text:
            ver += f" ↑{update_text}"
        return head + tail + stats + ver

    MUTE = _fg(theme.mute)
    EDGE = _fg(theme.edge)
    INK = _fg(theme.pill_ink)
    HOT = _fg(theme.s_warn)

    head = f"{MUTE}⤷ {info.project_name}{RESET}"
    if not info.in_git:
        body = f" {MUTE}{ITAL}(no git){RESET}"
    else:
        branch = info.branch or "?"
        if info.detached:
            branch_styled = f"{MUTE}{ITAL}{branch}{RESET}"
        else:
            branch_styled = f"{INK}{branch}{RESET}"
        dot = f"{HOT}●{RESET}" if dirty else ""
        body = f" {EDGE}⎇{RESET} {branch_styled}{dot}"
        if ab:
            # Soft accent (not bare mute) — a gentle "unpushed/behind work" nudge.
            body += f" {_fg(theme.s_ok)}{ab}{RESET}"
    if info.is_worktree:
        body += f" {MUTE}[worktree]{RESET}"
    # Version: the faintest thing on the line — edge (darkest grey) + dim
    # attribute, so it's there if you look for it but never competes for attention.
    ver = ""
    if version_text:
        ver = f" {FAINT}{EDGE}· v{version_text}{RESET}"
        # Update available → a soft amber `↑<newver>` nudge (a bit more visible
        # than the version, so you notice there's something to update to).
        if update_text:
            ver += f"{_fg(theme.s_warn)} ↑{update_text}{RESET}"
    return head + body + stats + ver


def render_activity_line(activity, *, theme: Theme, use_color: bool = True,
                         show_todos: bool = False, show_tools: bool = False,
                         show_tool_rollup: bool = False) -> str:
    """Render the optional 'activity' line — the in-turn signals only: the
    in-progress todo and the active tool + completed-tool rollup. Returns ""
    when nothing is enabled or present.

    Session stats (duration, lines) live on the identity line; subagents get
    their own bottom line(s) via ``render_agent_lines``.

    Style-agnostic (like ``render_identity_line``): the same line renders
    under classic / capsule / hairline so the curated main line is never
    disturbed.
    """
    MUTE = _fg(theme.mute)
    INK  = _fg(theme.ink)
    OK   = _fg(theme.s_ok)
    WARN = _fg(theme.s_warn)

    segs = []

    if show_todos and activity is not None and activity.todos:
        done, total = activity.todos_done, activity.todos_total
        ip = activity.in_progress_todo
        if ip:
            task = ip if len(ip) <= 28 else ip[:27] + "…"
            segs.append(f"{OK}▸{RESET} {INK}{task}{RESET} {MUTE}({done}/{total}){RESET}")
        else:
            segs.append(f"{OK}▸{RESET} {MUTE}todos {done}/{total}{RESET}")

    if show_tools and activity is not None and activity.active_tool:
        name, target = activity.active_tool
        tail = f" {MUTE}{target}{RESET}" if target else ""
        segs.append(f"{WARN}◐{RESET} {INK}{name}{RESET}{tail}")

    if show_tool_rollup and activity is not None and activity.completed_counts:
        # Tool name brightened (ink), ×count muted — scannable hierarchy.
        roll = " ".join(f"{INK}{n}{RESET}{MUTE}×{c}{RESET}"
                        for n, c in activity.completed_counts[:3])
        segs.append(f"{OK}✓{RESET} {roll}")

    if not segs:
        return ""
    line = f" {MUTE}·{RESET} ".join(segs)
    if not use_color:
        return _strip(line)
    return line


def render_agent_lines(agents, *, theme: Theme, use_color: bool = True) -> list:
    """One line per running subagent: `◐ <name>[<model>] <description> <elapsed>`.

    Each agent gets its own bottom line (multiple agents → multiple lines), so a
    long task description doesn't crowd the activity line. Returns [] when empty.
    """
    from .activity import format_elapsed_short

    if not agents:
        return []
    MUTE = _fg(theme.mute)
    INK  = _fg(theme.ink)
    WARN = _fg(theme.s_warn)

    lines = []
    for ag in agents:
        model = ag.get("model") or ""
        badge = f"{MUTE}[{model}]{RESET}" if model else ""
        desc = str(ag.get("description") or "").strip()
        if len(desc) > 40:  # roomier than the activity line — it's a line of its own
            desc = desc[:39] + "…"
        desc_part = f" {MUTE}{desc}{RESET}" if desc else ""
        el = format_elapsed_short(ag.get("elapsed_seconds", 0))
        line = (f"{WARN}◐{RESET} {INK}{ag.get('name', 'agent')}{RESET}{badge}"
                f"{desc_part} {MUTE}{el}{RESET}")
        lines.append(_strip(line) if not use_color else line)
    return lines


# Per-effort gradient palettes — a MONOTONIC grey→blue→purple ladder matching
# Claude Code's own "Faster → Smarter" effort slider (low … max, then ultracode
# = xhigh+workflows as the distinct vivid-purple top). Each tier is visibly more
# saturated/purple than the one below, so the level reads as an ordered ladder
# (not the old rainbow, where coral `max` looked hotter than `ultracode`).
_EFFORT_GRADIENTS = {
    "low":       [(56, 190, 184), (110, 215, 205)],              # teal → aqua (coolest)
    "auto":      [(56, 190, 184), (110, 215, 205)],              # neutral, like low
    "medium":    [(64, 150, 236), (120, 180, 244)],              # azure → sky
    "high":      [(92, 120, 242), (140, 160, 248)],              # blue → periwinkle
    "xhigh":     [(140, 108, 244), (178, 150, 250)],             # indigo → lilac
    "max":       [(186, 100, 240), (214, 148, 248)],             # violet → orchid
    "ultracode": [(228, 108, 224), (248, 150, 238)],             # magenta → pink (vivid top)
}
# Fallback for unknown/future levels — the showcase vivid purple.
_MODE_GRADIENT_STOPS = _EFFORT_GRADIENTS["ultracode"]


def _effort_gradient_stops(level):
    return _EFFORT_GRADIENTS.get(str(level).strip().lower(), _MODE_GRADIENT_STOPS)


def _lerp_rgb(a, b, f):
    return tuple(int(round(a[i] + (b[i] - a[i]) * f)) for i in range(3))


def _grad_sample(stops, f):
    """Sample a NON-cyclic gradient at f∈[0,1] across `stops` (clamped ends)."""
    if f <= 0:
        return stops[0]
    if f >= 1:
        return stops[-1]
    x = f * (len(stops) - 1)
    i = int(x)
    return _lerp_rgb(stops[i], stops[i + 1], x - i)


def _gradient_text(text: str, stops=None) -> str:
    """A single STATIC gradient (palette `stops`) swept once across `text`, left
    to right. Not animated: the statusLine refreshes at ≤1 Hz (and event-driven
    in some builds), so any motion can only step ~1/s and reads as a flicker —
    a clean stable sweep is the right call. The per-effort palette tells the tier."""
    stops = stops or _MODE_GRADIENT_STOPS
    n = len(text)
    out = [
        _fg(_grad_sample(stops, i / max(1, n - 1))) + ch
        for i, ch in enumerate(text)
    ]
    return "".join(out) + RESET


def _effort_display(level) -> str:
    """Display string for the effort value. `ultracode` spells out what it means
    (Claude Code: `ultracode = xhigh + workflows`); everything else verbatim."""
    if str(level).strip().lower() == "ultracode":
        return f"{level}(+workflows)"
    return str(level)


def _effort_color(level, theme):
    """Colour the effort value by intensity tier (not severity): top tiers get a
    soft amber 'cranked up' nudge, low/auto recede, the rest stay neutral. Values
    are Claude Code's: low / medium / high / xhigh / max / ultracode / auto."""
    lv = str(level).strip().lower()
    if lv in ("xhigh", "max", "ultracode"):
        return _fg(theme.s_warn)
    if lv in ("low", "auto", ""):
        return _fg(theme.mute)
    return _fg(theme.ink)   # medium / high / unknown future values


def render_mode_line(*, effort: str = "", thinking=None, fast=None,
                     style: str = "", theme: Theme, use_color: bool = True,
                     gradient: bool = True) -> str:
    """Session-mode readout: `⚙ effort:high · think:on · fast:on · style:default`.

    Each field is dropped when absent, so an older Claude Code that omits one
    just shows fewer segments; returns '' when nothing is known. The effort value
    is shown verbatim (handles any of low/medium/high/xhigh/max/ultracode/auto and
    future values) and tinted by intensity. When `gradient` is on (default), the
    WHOLE line gets a static gradient whose palette depends on the effort tier
    (cool→hot: slate/blue/cyan/amber/coral/pink-purple), so the tier is obvious at
    a glance. Static, not animated — the statusLine can't repaint faster than ~1 Hz,
    so motion only flickers; a stable per-tier sweep is the clean result."""
    segs = []  # (label, value, value_color)
    if effort:
        segs.append(("effort:", _effort_display(effort), _effort_color(effort, theme)))
    if thinking is not None:
        segs.append(("think:", "on" if thinking else "off", _fg(theme.ink)))
    if fast is not None:
        segs.append(("fast:", "on" if fast else "off", _fg(theme.ink)))
    if style:
        segs.append(("style:", str(style), _fg(theme.ink)))
    if not segs:
        return ""
    plain = "⚙ " + " · ".join(f"{l}{v}" for l, v, _ in segs)
    if not use_color:
        return plain
    if gradient:
        return _gradient_text(plain, _effort_gradient_stops(effort))
    MUTE = _fg(theme.mute)
    body = f"{MUTE} · {RESET}".join(
        f"{MUTE}{l}{RESET}{c}{v}{RESET}" for l, v, c in segs)
    return f"{MUTE}⚙{RESET} " + body


RENDERERS = {
    "classic":  render_classic,
    "capsule":  render_capsule,
    "hairline": render_hairline,
}


def is_known_style(style: str) -> bool:
    return style in RENDERERS


def render(style: str, **kwargs) -> str:
    """Render with the named style. Unknown style names fall back to classic.

    Unknown kwargs are absorbed by each renderer's **_ignored, so callers can
    freely pass style-specific args (density, countdown_emoji, ...) to whichever
    renderer is selected.

    The optional `show_project_branch`/`identity`/`identity_dirty` kwargs
    cause a second `⤷ <project> ⎇ <branch>` line to be appended after the
    style renderer returns. The optional `activity`/`activity_opts` kwargs
    append an 'activity' line (todos / active tool / session stats) plus one
    bottom line per running subagent. All extra lines are style-agnostic.
    """
    show_pb = kwargs.pop("show_project_branch", False)
    info = kwargs.pop("identity", None)
    dirty = kwargs.pop("identity_dirty", None)
    ahead = kwargs.pop("identity_ahead", None)
    behind = kwargs.pop("identity_behind", None)
    duration_text = kwargs.pop("identity_duration", "")
    lines_text = kwargs.pop("identity_lines", "")
    show_version = kwargs.pop("identity_show_version", False)
    show_mode = kwargs.pop("mode_show", False)
    mode_effort = kwargs.pop("mode_effort", "")
    mode_thinking = kwargs.pop("mode_thinking", None)
    mode_fast = kwargs.pop("mode_fast", None)
    mode_style = kwargs.pop("mode_style", "")
    mode_gradient = kwargs.pop("mode_gradient", True)
    kwargs.pop("mode_phase", None)   # accepted for back-compat; gradient is static
    activity = kwargs.pop("activity", None)
    activity_opts = kwargs.pop("activity_opts", None)
    theme = kwargs.get("theme") or get_theme("graphite")
    use_color = kwargs.get("use_color", True)

    fn = RENDERERS.get(style, render_classic)
    out = fn(**kwargs)

    if show_pb and info is not None:
        version_text = _statusbar_version() if show_version else ""
        update_text = _update_hint() if show_version else ""
        out = out + "\n" + render_identity_line(
            info, theme=theme, dirty=dirty, ahead=ahead, behind=behind,
            duration_text=duration_text, lines_text=lines_text,
            version_text=version_text, update_text=update_text,
            use_color=use_color,
        )

    if show_mode:
        mode_line = render_mode_line(
            effort=mode_effort, thinking=mode_thinking, fast=mode_fast,
            style=mode_style, theme=theme, use_color=use_color,
            gradient=mode_gradient)
        if mode_line:
            out = out + "\n" + mode_line

    if activity_opts:
        opts = dict(activity_opts)
        show_agents = opts.pop("show_agents", False)
        act_line = render_activity_line(
            activity, theme=theme, use_color=use_color, **opts)
        if act_line:
            out = out + "\n" + act_line
        # Subagents get their own bottom line(s), one per running agent.
        if show_agents and activity is not None and activity.agents:
            for agline in render_agent_lines(
                    activity.agents, theme=theme, use_color=use_color):
                out = out + "\n" + agline
    return out


def list_styles() -> list[str]:
    return list(RENDERERS.keys())
