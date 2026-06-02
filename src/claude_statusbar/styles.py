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
        return head + tail + stats

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
    return head + body + stats


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
    activity = kwargs.pop("activity", None)
    activity_opts = kwargs.pop("activity_opts", None)
    theme = kwargs.get("theme") or get_theme("graphite")
    use_color = kwargs.get("use_color", True)

    fn = RENDERERS.get(style, render_classic)
    out = fn(**kwargs)

    if show_pb and info is not None:
        out = out + "\n" + render_identity_line(
            info, theme=theme, dirty=dirty, ahead=ahead, behind=behind,
            duration_text=duration_text, lines_text=lines_text,
            use_color=use_color,
        )

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
