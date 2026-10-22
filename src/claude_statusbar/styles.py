"""Status-line layout renderers (style = layout, theme = palette).

Each renderer takes the same set of fields as ``progress.format_status_line``
plus a Theme, and returns the final ANSI string.

Adding a new style:
    1. Define ``render_<name>(...) -> str``
    2. Register it in ``RENDERERS``.
"""

from typing import Optional

from ._display import clip_line, clip_lines, visible_width
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

# strip ANSI when use_color is False
import re as _re
_ANSI_RE = _re.compile(r"\033\[[0-9;]*m")
def _strip(s: str) -> str: return _ANSI_RE.sub("", s)


def _attr(obj, name: str, default=""):
    return getattr(obj, name, default)

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
# Style: aurora — ■ (or thin ━) bars whose cells blend ok→warn→hot by position
# ---------------------------------------------------------------------------
_AURORA_TOKENS_RE = _re.compile(r"\s*\([^()\n]*\)$")
_AURORA_SECS_RE = _re.compile(r"(\d+)m\d+s$")


def _aurora_cache_text(text: str) -> str:
    """Drop the seconds once they stop mattering: `1h00m00s` → `1h00m`,
    `59m12s` → `59m`. Under 10 minutes the seconds stay (`4m23s`)."""
    m = _AURORA_SECS_RE.search(text)
    if m and ("h" in text or int(m.group(1)) >= 10):
        return text[:m.end(1)] + "m"
    return text


def render_aurora(
    *, msgs_pct, weekly_pct, reset_5h, reset_7d, model,
    lang_body="", cost_text="", cache_age_text="", bypass=False,
    use_color=True, theme: Optional[Theme]=None,
    warning_threshold=30.0, critical_threshold=70.0,
    density: str = "regular",
    bar_glyph: str = "block",
    show_weekly: bool = True,
    ctx_pct: Optional[float] = None,
    projection_5h: str = "",
    projection_7d: str = "",
    forecast_5h: str = "",
    forecast_7d: str = "",
    countdown_emoji: str = "",
    no_quota: bool = False,
    balance_text: str = "",
    quota_stale: bool = False,
    stack_quotas: bool = False,
    **_ignored,
) -> str:
    from .progress import (window_severity_rgb, _blend, projection_pct,
                           _render_projection, _render_forecast,
                           CONTEXT_WARNING_THRESHOLD as _CW,
                           CONTEXT_CRITICAL_THRESHOLD as _CC)
    theme = theme or get_theme("graphite")
    INK  = _fg(theme.ink)
    MUTE = _fg(theme.mute)
    EDGE = _fg(theme.edge)
    cell = "━" if bar_glyph == "thin" else "■"

    def bar(p, width):
        # Each cell's color is fixed by its position along the bar, so a fuller
        # bar literally reaches further into the red end of the spectrum.
        if p is None:
            return f"{EDGE}{cell * width}{RESET}"
        clamped = max(0.0, min(float(p), 100.0))
        filled = int(clamped / 100 * width + 0.5)
        if p > 0 and filled == 0:
            filled = 1
        out = ""
        for i in range(width):
            if i < filled:
                t = i / (width - 1) if width > 1 else 0.0
                rgb = (_blend(theme.s_ok, theme.s_warn, t * 2) if t < 0.5
                       else _blend(theme.s_warn, theme.s_hot, (t - 0.5) * 2))
                out += f"{_fg(rgb)}{cell}"
            else:
                out += f"{EDGE}{cell}"
        return out + RESET

    def pct_text(p, rgb):
        if p is None:
            return f"{MUTE}--%{RESET}"
        col = _fg(rgb) if rgb is not None else INK
        return f"{col}{BOLD}{int(round(p)):>2}%{RESET}"

    def window(label, p, chip, forecast, reset, emoji=""):
        rgb = window_severity_rgb(p, chip, theme,
                                  warning_threshold, critical_threshold)
        out = (f"{MUTE}{label:>2}{RESET} {bar(p, 12)} {pct_text(p, rgb)} "
               f"{EDGE}⏰{MUTE}{reset or '--'}{emoji}{RESET}")
        if chip:
            out += " " + _render_projection(chip, theme, True)
        # Same rule as classic: a usable projection wins over the ⚠ forecast.
        if forecast and projection_pct(chip) is None:
            out += " " + _render_forecast(forecast, theme, True)
        return out

    sep_pad = DENSITY_PAD.get(density, " ")
    sep = f"{sep_pad}{EDGE}│{RESET}{sep_pad}"
    quota_parts = []
    parts = []

    if no_quota:
        rgb = _severity_color(theme, ctx_pct, _CW, _CC)
        parts.append(f"{MUTE}ctx{RESET} {bar(ctx_pct, 12)} {pct_text(ctx_pct, rgb)}")
    elif quota_stale and msgs_pct is None and weekly_pct is None:
        parts.append(f"{_fg(theme.s_warn)}⟳ 5h/7d stale·restart{RESET}")
    else:
        quota_parts.append(window("5h", msgs_pct, projection_5h, forecast_5h,
                                 reset_5h, countdown_emoji))
        if show_weekly:
            quota_parts.append(window("7d", weekly_pct, projection_7d, forecast_7d,
                                      reset_7d))

    # The mini bar carries context fill, so the `(70.0k/1.0M)` suffix is
    # redundant here; no_quota already shows ctx as the lead segment.
    # A rose between the hot and worktree hues — reads as "the model", never
    # as a severity, and follows each theme's palette.
    accent = _fg(_blend(theme.s_hot, theme.wt, 0.5))
    if ctx_pct is not None and not no_quota:
        name = _AURORA_TOKENS_RE.sub("", str(model))
        rgb = _severity_color(theme, ctx_pct, _CW, _CC)
        parts.append(f"{accent}{name}{RESET} {bar(ctx_pct, 6)} "
                     f"{_fg(rgb)}{int(round(ctx_pct))}%{RESET}")
    else:
        parts.append(f"{accent}{model}{RESET}")

    if balance_text:
        parts.append(f"{_fg(theme.s_ok)}{balance_text}{RESET}")
    if cost_text:
        parts.append(f"{MUTE}$ {INK}{cost_text}{RESET}")

    if lang_body:
        parts.append(f"{MUTE}{lang_body}{RESET}")

    if cache_age_text:
        col = _fg(_cache_severity(theme, cache_age_text))
        parts.append(f"{col}❄ {_aurora_cache_text(cache_age_text)}{RESET}")

    if bypass:
        parts.append(f"{_fg(theme.s_hot)}{BOLD}⚠ BYPASS{RESET}")

    if stack_quotas and quota_parts:
        line = "\n".join(quota_parts + [sep.join(parts)])
        if not use_color:
            return _strip(line)
        return line
    line = sep.join(quota_parts + parts)
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
    no_quota: bool = False,
    balance_text: str = "",
    balance_pct=None,
    balance_amount: str = "",
    quota_stale: bool = False,
    stack_quotas: bool = False,
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
        no_quota=no_quota,
        balance_text=balance_text,
        balance_pct=balance_pct,
        balance_amount=balance_amount,
        quota_stale=quota_stale,
        stack_quotas=stack_quotas,
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


def _worktree_label(info, glyph: str = "🌳") -> str:
    """Display name for a linked worktree checkout.

    The worktree's own name, with a redundant repo prefix trimmed
    (``repo-wt-x`` → ``wt-x``) since the repo already anchors the line.
    Falls back to a bare ``worktree`` when the name is unknown, or when it
    would only repeat the branch / repo already printed next to it.
    """
    name = (getattr(info, "worktree_name", None) or "").strip()
    if not name:
        return "worktree"
    from .identity import strip_repo_prefix  # lazy: keeps the hot path lean
    project = (getattr(info, "project_name", "") or "").strip()
    name = strip_repo_prefix(name, project)
    if name in (project, (getattr(info, "branch", "") or "")):
        name = "worktree"
    # Total linked worktrees on this repo, this one included — the thing you
    # actually forget once you keep parallel checkouts around. A plain total,
    # not an ordinal: "which one of N am I" is already answered by the name.
    total = getattr(info, "worktree_count", 0) or 0
    return f"{name} ({glyph}{total})" if total else name


def render_identity_line(info, *, theme: Theme, dirty,
                         ahead=None, behind=None,
                         duration_text: str = "", lines_text: str = "",
                         version_text: str = "", update_text: str = "",
                         cwd_text: str = "",
                         worktree_glyph: str = "🌳",
                         lang: str = "en",
                         use_color: bool = True) -> str:
    """Render the 2nd line: `⤷ <project> ⎇ <branch>●↑2↓1 · ⏱ <dur> · +/-lines`.

    `dirty` is True / False / None — None means "unknown" (cache miss);
    in that case we omit the dot rather than asserting clean. `ahead`/`behind`
    are commits relative to upstream (None = unknown/no upstream, 0 = in sync);
    arrows render only for nonzero directions and only inside a git repo.
    `duration_text`/`lines_text` are the session stats, shown here (next to the
    project) rather than on the live-activity line. When the checkout is a
    linked git worktree (`info.is_worktree`), a ``<name> (🌳N)`` marker in the
    theme's dedicated worktree hue (`theme.wt`) *leads* the line — before the
    repo — so "I am not in the main checkout" is the first thing read, never
    something you scan past. The name collapses to a bare ``⧉ worktree`` when
    it would only repeat the branch or the repo.

    `cwd_text` (show_cwd, #30) is the session's working directory; it's
    appended after the branch only when it adds information — skipped when it
    equals the project name (cwd at the repo root would just repeat the anchor).
    """
    main_label = "worktree"  # same word in zh and en (leo, 2026-10-22)
    ab = _ahead_behind_glyphs(ahead, behind) if info.in_git else ""
    stats = _stats_segment(duration_text, lines_text, theme=theme,
                           use_color=use_color)

    if not use_color:
        head = f"⤷ {info.project_name}"
        if info.is_worktree:
            head = f"{_worktree_label(info, worktree_glyph)} {head}"
        elif info.in_git:
            head = f"{main_label} ({worktree_glyph}{info.worktree_count}) {head}"
        if not info.in_git:
            tail = " (no git)"
        else:
            branch = info.branch or "?"
            dot = "●" if dirty else ""
            tail = f" ⎇ {branch}{dot}"
            if ab:
                tail += f" {ab}"
        if cwd_text and cwd_text != info.project_name:
            tail += f" · {cwd_text}"
        ver = f" · v{version_text}" if version_text else ""
        if version_text and update_text:
            ver += f" ↑{update_text}"
        return head + tail + stats + ver

    MUTE = _fg(theme.mute)
    EDGE = _fg(theme.edge)
    INK = _fg(theme.pill_ink)
    HOT = _fg(theme.s_warn)

    # Project name in full ink — it's the line's identity anchor (user
    # feedback 2026-07-02: mute made it near-invisible). The ⤷ stays mute.
    head = f"{MUTE}⤷ {RESET}{INK}{info.project_name}{RESET}"
    if info.is_worktree:
        # Leads the line, in its own hue — not mute: "this is not the main
        # checkout" is the one fact here you must never scan past (it's what
        # stops a commit landing on the wrong tree).
        head = (f"{_fg(theme.wt)}{_worktree_label(info, worktree_glyph)}"
                f"{RESET} " + head)
    elif info.in_git:
        # Main checkout: always report, `(0)` included. An omitted marker and
        # a zero count look identical, and "is it broken or is it zero?" got
        # asked four times before this line existed. Same tree glyph as a
        # worktree — the *name* is what differs — but dimmed, because being in
        # the trunk is the ordinary case and only a worktree is a warning.
        head = (f"{FAINT}{_fg(theme.wt)}{main_label} "
                f"({worktree_glyph}{info.worktree_count}){RESET} " + head)
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
    if cwd_text and cwd_text != info.project_name:
        body += f" {MUTE}·{RESET} {INK}{cwd_text}{RESET}"
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


def _aurora_quiet(theme: Theme):
    """Palette for aurora's lines below the first: line 1 carries the color,
    these recede — grey text, with severity hues sunk halfway into mute."""
    from .progress import _blend
    return dict(
        BASE=_fg(_blend(theme.pill_ink, theme.mute, 0.5)),
        DIM=_fg(theme.mute),
        EDGE=_fg(theme.edge),
        soft=lambda rgb: _fg(_blend(rgb, theme.mute, 0.45)),
    )


# Lines below aurora's first use a faint dot, not `│`: stacked `│`s at
# unrelated offsets read as a misaligned table.
_QUIET_SEP = "  ·  "


def render_identity_line_aurora(info, *, theme: Theme, dirty,
                                ahead=None, behind=None,
                                duration_text: str = "", lines_text: str = "",
                                version_text: str = "", update_text: str = "",
                                cwd_text: str = "",
                                worktree_glyph: str = "🌳",
                                lang: str = "en",
                                use_color: bool = True) -> str:
    """Aurora's 2nd line: `⎇ main ●↓1  ·  project  ·  +244 −3  ·  ⏱ 4m`, muted.

    Same facts as `render_identity_line`, regrouped behind `│` separators with
    the branch leading. A linked worktree still leads the whole line; the trunk
    marker appears only when other worktrees exist, the version only when an
    update is waiting.
    """
    main_label = "worktree"  # same word in zh and en (leo, 2026-10-22)
    q = _aurora_quiet(theme)
    BASE, DIM, EDGE, soft = q["BASE"], q["DIM"], q["EDGE"], q["soft"]
    from ._display import hyperlink
    from .identity import branch_web_url
    repo_url = getattr(info, "web_url", None)

    def c(color, text):
        return f"{color}{text}{RESET}" if use_color else text

    def link(text, url):
        # Cmd/Ctrl+click opens it; plain-text output stays link-free.
        return hyperlink(text, url) if use_color else text

    segs = []
    if info.is_worktree:
        segs.append(c(soft(theme.wt), _worktree_label(info, worktree_glyph)))
    if info.in_git:
        branch = info.branch or "?"
        head = c(DIM, "⎇ ") + link(c(f"{DIM}{ITAL}" if info.detached else BASE, branch),
                                   None if info.detached else branch_web_url(repo_url, branch))
        flags = ("●" if dirty else "") + _ahead_behind_glyphs(ahead, behind)
        if flags:
            head += " " + c(soft(theme.s_warn), flags)
        segs.append(head)
    segs.append(link(c(BASE, info.project_name), repo_url))
    if not info.in_git:
        segs.append(c(f"{DIM}{ITAL}", "no git"))
    if cwd_text and cwd_text != info.project_name:
        segs.append(c(BASE, cwd_text))
    if lines_text:
        toks = []
        for tok in lines_text.split():
            if tok.startswith("+"):
                toks.append(c(soft(theme.s_ok), tok))
            elif tok.startswith("-"):
                toks.append(c(soft(theme.s_hot), "−" + tok[1:]))
            else:
                toks.append(c(DIM, tok))
        segs.append(" ".join(toks))
    if duration_text:
        segs.append(c(DIM, f"⏱ {duration_text}"))
    if info.in_git and not info.is_worktree and info.worktree_count:
        segs.append(c(DIM, f"{main_label} ({worktree_glyph}{info.worktree_count})"))
    if version_text and update_text:
        notes = ("https://github.com/leeguooooo/claude-code-usage-bar/releases/tag/"
                 f"v{update_text}")
        segs.append(c(DIM, f"v{version_text}")
                    + link(c(soft(theme.s_warn), f" ↑{update_text}"), notes))
    return c(EDGE, _QUIET_SEP).join(segs)


def render_ocs_line_aurora(ocs_text: str, unread, lan, *, theme: Theme,
                           use_color: bool = True, lang: str = "en") -> str:
    """`ocs claude-b2242a10  ·  3 unread  ·  lan ● win  ● mac`, muted like line 2.
    Unread is a word, not ✉ — the envelope renders as a mismatched emoji."""
    q = _aurora_quiet(theme)
    BASE, DIM, EDGE, soft = q["BASE"], q["DIM"], q["EDGE"], q["soft"]

    def c(color, text):
        return f"{color}{text}{RESET}" if use_color else text

    name, sep, ident = ocs_text.partition(" · ")
    segs = [c(DIM, "ocs ") + c(BASE, name) + (c(DIM, f" {ident}") if sep else "")]
    if unread:
        segs.append(c(soft(theme.s_warn),
                      f"{unread} 条未读" if lang == "zh" else f"{unread} unread"))
    if lan:
        if not lan.get("running"):
            segs.append(c(DIM, "lan ") + c(soft(theme.s_warn), "off"))
        else:
            peers = [c(soft(theme.s_ok) if recent else EDGE, "●") + " "
                     + c(BASE if recent else DIM, label)
                     for label, recent in (lan.get("peers") or [])]
            body = "  ".join(peers) if peers else c(DIM, "on")
            if lan.get("more"):
                body += c(DIM, f" +{lan['more']}")
            segs.append(c(DIM, "lan ") + body)
    return c(EDGE, _QUIET_SEP).join(segs)


def _ocs_segment(ocs_text: str, theme: Theme) -> str:
    """`ocs boss · claude-7d5a5d07`: the `ocs` tag in edge grey, the name in
    ink (the thing you'd type), the stable id muted."""
    EDGE = _fg(theme.edge)
    INK = _fg(theme.pill_ink)
    MUTE = _fg(theme.mute)
    name, sep, ident = ocs_text.partition(" · ")
    if sep:
        return (f"{EDGE}ocs{RESET} {INK}{name}{RESET} "
                f"{MUTE}· {ident}{RESET}")
    return f"{EDGE}ocs{RESET} {INK}{ocs_text}{RESET}"


def _ocs_extras(unread, lan, theme: Theme, use_color: bool) -> str:
    """` · ✉3 · lan win` — unread DMs in warn, LAN peers seen recently in ink,
    stale ones muted, a stopped bridge that still has peers as `lan off`."""
    parts = []
    if unread:
        parts.append(f"{_fg(theme.s_warn)}✉{unread}{RESET}" if use_color
                     else f"✉{unread}")
    if lan:
        if not lan.get("running"):
            parts.append(f"{_fg(theme.edge)}lan{RESET} {_fg(theme.s_warn)}off{RESET}"
                         if use_color else "lan off")
        else:
            peers = lan.get("peers") or []
            if use_color:
                names = " ".join(
                    f"{_fg(theme.pill_ink if recent else theme.mute)}{label}{RESET}"
                    for label, recent in peers)
            else:
                names = " ".join(label for label, _recent in peers)
            if lan.get("more"):
                more = f"+{lan['more']}"
                names += " " + (f"{_fg(theme.mute)}{more}{RESET}" if use_color else more)
            if not peers:
                names = f"{_fg(theme.mute)}on{RESET}" if use_color else "on"
            parts.append((f"{_fg(theme.edge)}lan{RESET} " if use_color else "lan ")
                         + names)
    if not parts:
        return ""
    sep = f" {_fg(theme.mute)}·{RESET} " if use_color else " · "
    return sep + sep.join(parts)


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


def _clip_width(s: str, limit: int) -> str:
    """Back-compatible wrapper around shared ANSI-aware clipping."""
    return clip_line(s, limit)


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
    # DESATURATED cool→purple ladder — each tier sweeps toward the next hue so it
    # reads as a gradient, but the colours are dusty/low-saturation so the line
    # doesn't shout next to the rest of the (restrained) bar. ultracode is a touch
    # brighter as the top tier.
    "low":       [(120, 172, 168), (124, 158, 196)],             # dusty teal → blue
    "auto":      [(120, 172, 168), (124, 158, 196)],             # neutral, like low
    "medium":    [(122, 156, 198), (132, 146, 202)],             # dusty azure
    "high":      [(130, 144, 204), (156, 140, 202)],             # dusty blue → indigo
    "xhigh":     [(152, 138, 204), (176, 134, 200)],             # dusty indigo → violet
    "max":       [(176, 134, 200), (196, 138, 196)],             # dusty violet → mauve
    "ultracode": [(200, 138, 202), (220, 160, 208)],             # dusty magenta → pink (top)
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
    "aurora":   render_aurora,
    "classic":  render_classic,
}


def is_known_style(style: str) -> bool:
    return style in RENDERERS


def render(style: str, **kwargs) -> str:
    """Render with the named style. Unknown style names (including the
    capsule / hairline styles removed in 3.50.0) fall back to aurora.

    Unknown kwargs are absorbed by each renderer's **_ignored, so callers can
    freely pass style-specific args (density, countdown_emoji, ...) to whichever
    renderer is selected.

    The optional `show_project_branch`/`identity`/`identity_dirty` kwargs
    cause a second `⤷ <project> ⎇ <branch>` line to be appended after the
    style renderer returns. The optional `activity`/`activity_opts` kwargs
    append an 'activity' line (todos / active tool / session stats) plus one
    bottom line per running subagent. All extra lines are style-agnostic.
    """
    max_width = kwargs.pop("max_width", None)
    narrow_layout = kwargs.pop("narrow_layout", "clip")
    show_pb = kwargs.pop("show_project_branch", False)
    info = kwargs.pop("identity", None)
    dirty = kwargs.pop("identity_dirty", None)
    ahead = kwargs.pop("identity_ahead", None)
    behind = kwargs.pop("identity_behind", None)
    duration_text = kwargs.pop("identity_duration", "")
    lines_text = kwargs.pop("identity_lines", "")
    cwd_text = kwargs.pop("cwd_text", "")
    ocs_text = kwargs.pop("ocs_text", "")
    ocs_unread = kwargs.pop("ocs_unread", None)
    ocs_lan = kwargs.pop("ocs_lan", None)
    worktree_glyph = kwargs.pop("worktree_glyph", "🌳")
    looks_hint = kwargs.pop("looks_hint", False)
    ip_line_text = kwargs.pop("ip_line_text", "")
    ip_line_level = kwargs.pop("ip_line_level", "ok")
    fp_line_text = kwargs.pop("fp_line_text", "")
    fp_line_level = kwargs.pop("fp_line_level", "ok")
    ip_finding = kwargs.pop("ip_finding", None)
    fp_finding = kwargs.pop("fp_finding", None)
    ui_lang = (kwargs.pop("ui_lang", None) or kwargs.pop("risk_lang", None)
               or kwargs.pop("fp_lang", None) or "en")
    kwargs.pop("risk_lang", None)
    kwargs.pop("fp_lang", None)
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
    per_model_limits = kwargs.pop('per_model_limits', [])
    per_model_projection = kwargs.pop('per_model_projection', True)
    theme = kwargs.get("theme") or get_theme("graphite")
    use_color = kwargs.get("use_color", True)

    fn = RENDERERS.get(style, render_aurora)
    render_kwargs = dict(kwargs)
    out = fn(**render_kwargs)
    scoped = ""
    if per_model_limits:
        from .scoped_usage import render_limits
        scoped = render_limits(per_model_limits, theme, use_color,
                               kwargs.get('warning_threshold'),
                               kwargs.get('critical_threshold'), per_model_projection)
        if scoped:
            out += '\n' + scoped

    def rerender():
        rendered = fn(**render_kwargs)
        return rendered + ("\n" + scoped if scoped else "")

    # Preserve core quota/model signal before hard clipping. Optional segments
    # disappear in stable least-important-first order; selected style stays put.
    if (max_width is not None and max_width > 0
            and visible_width(out.split("\n", 1)[0]) > max_width):
        stacked = False
        if narrow_layout == "stack":
            render_kwargs["stack_quotas"] = True
            out = rerender()
            stacked = "\n" in out

        def fits(text):
            if stacked and scoped and text.endswith("\n" + scoped):
                text = text[:-(len(scoped) + 1)]
            lines = text.splitlines() if stacked else text.split("\n", 1)[:1]
            return all(visible_width(line) <= max_width for line in lines)

        degradation = (
            {"cache_age_text": ""},
            {"lang_body": ""},
            {"cost_text": ""},
            {"balance_text": "", "balance_pct": None, "balance_amount": ""},
            {"forecast_5h": "", "forecast_7d": ""},
            {"projection_5h": "", "projection_7d": ""},
        )
        if not fits(out):
            for replacements in degradation:
                render_kwargs.update(replacements)
                out = rerender()
                if fits(out):
                    break
            else:
                # Context tokens go last, and in two steps: drop the window
                # denominator first — "Opus 5(139.3k/1.0M)" → "Opus 5(139.3k)" buys
                # ~6 columns and keeps the number people actually read. A ~70-col
                # pane on a 1M-context model lands exactly here, so dropping
                # straight to a bare model name loses the count for no reason.
                import re
                model = str(render_kwargs.get("model", ""))
                m = re.search(r"\s*\(([^()\n]*)/[^()\n]*\)$", model)
                if m:
                    head = model[:m.start()]
                    for candidate in (f"{head}({m.group(1)})", head):
                        render_kwargs["model"] = candidate
                        out = rerender()
                        if fits(out):
                            break

    if show_pb and info is not None:
        version_text = _statusbar_version() if show_version else ""
        update_text = _update_hint() if show_version else ""
        identity_fn = (render_identity_line_aurora if style == "aurora"
                       else render_identity_line)
        out = out + "\n" + identity_fn(
            info, theme=theme, dirty=dirty, ahead=ahead, behind=behind,
            duration_text=duration_text, lines_text=lines_text,
            version_text=version_text, update_text=update_text,
            cwd_text=cwd_text,
            worktree_glyph=worktree_glyph,
            lang=ui_lang,
            use_color=use_color,
        )
    elif cwd_text:
        # show_cwd is on but the identity line is off — give the directory its
        # own minimal line, styled like the identity anchor.
        if use_color:
            out = (out + "\n" + f"{_fg(theme.mute)}⤷ {RESET}"
                   f"{_fg(theme.pill_ink)}{cwd_text}{RESET}")
        else:
            out = out + "\n" + f"⤷ {cwd_text}"
    if ocs_text and style == "aurora":
        out = out + "\n" + render_ocs_line_aurora(
            ocs_text, ocs_unread, ocs_lan, theme=theme, use_color=use_color,
            lang=ui_lang)
    elif ocs_text:
        # Always its own line — the address other agents copy, not branch info.
        out = out + "\n" + (_ocs_segment(ocs_text, theme) if use_color
                            else f"ocs {ocs_text}")
        out += _ocs_extras(ocs_unread, ocs_lan, theme, use_color)

    # Dedicated egress-IP risk warning — appears only above the risk threshold
    # (ip_risk.SHOW_THRESHOLD), amber for suspicious, red for bad. May be
    # multi-line (summary + action); each sub-line is colored separately, then
    # final width clipping applies per physical line. Not part of git identity.
    def _emit_risk(text, level, finding=None):
        nonlocal out
        if finding is not None:
            from .risk_line import format_finding
            out = out + "\n" + format_finding(finding, theme=theme, lang=ui_lang,
                                              use_color=use_color)
            return
        if not text:
            return
        color = theme.s_hot if level == "crit" else theme.s_warn
        for seg in text.split("\n"):
            out = out + "\n" + (f"{_fg(color)}{seg}{RESET}" if use_color else seg)

    if looks_hint:
        from .picker import hint_text
        text = hint_text(ui_lang)
        out = out + "\n" + (f"{_fg(theme.mute)}{text}{RESET}" if use_color else text)

    _emit_risk(ip_line_text, ip_line_level, ip_finding)
    # Custom-endpoint notice (local env inference; see fp_risk.py).
    _emit_risk(fp_line_text, fp_line_level, fp_finding)

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
    return clip_lines(out, max_width)


def list_styles() -> list[str]:
    return list(RENDERERS.keys())
