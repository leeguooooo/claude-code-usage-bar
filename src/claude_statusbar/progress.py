"""Progress bar rendering for the status bar. Pure functions, no I/O."""

import json
import re
from pathlib import Path
from typing import Optional

from .themes import Theme, get_theme

FILL = "█"
EMPTY = "░"
RESET = "\033[0m"

DEFAULT_WARNING_THRESHOLD = 30.0
DEFAULT_CRITICAL_THRESHOLD = 70.0

# Rate-limit windows (5h / 7d) color by where they're HEADED, not where they
# are right now: once a `→NN%` end-of-window projection exists, the cap (100%)
# is the red line and near-cap is the warning. These are distinct from the
# configurable comfort thresholds above, which still drive the current-usage
# fallback (before a projection exists) and non-projected gauges like the
# context window. Red starts well below the cap on purpose: a projection of
# 85%+ means you're essentially going to run the window out (the chip clamps at
# 100, so "→99%" sits there for ages on the slow 7d window — it should read as
# alarming, not merely warm).
PROJECTION_WARNING_THRESHOLD = 70.0
PROJECTION_CRITICAL_THRESHOLD = 85.0

# Context-window bar (no-quota mode) uses claude-hud's thresholds — warn 70 /
# crit 85 on used% — NOT the 5h/7d comfort band. Context filling toward
# auto-compact is only concerning near the top, so 30% used must read calm
# (green), not warning. Borrowed verbatim from claude-hud's getContextColor.
CONTEXT_WARNING_THRESHOLD = 70.0
CONTEXT_CRITICAL_THRESHOLD = 85.0

# Relay-balance fuel gauge colors on *remaining* %, not used: full is green,
# getting low is yellow, nearly empty is red (a fuel/phone-battery mental model,
# the inverse of the context bar where a full bar is bad).
BALANCE_LOW_THRESHOLD = 25.0       # ≤25% left → yellow
BALANCE_CRITICAL_THRESHOLD = 10.0  # ≤10% left → red


def _balance_fill_rgb(remaining_pct, theme):
    """Fuel-gauge fill color from remaining balance %: green high → red low."""
    if remaining_pct <= BALANCE_CRITICAL_THRESHOLD:
        return theme.s_hot
    if remaining_pct <= BALANCE_LOW_THRESHOLD:
        return theme.s_warn
    return theme.s_ok


def _fg(rgb): return f"\033[38;2;{rgb[0]};{rgb[1]};{rgb[2]}m"
def _bg(rgb): return f"\033[48;2;{rgb[0]};{rgb[1]};{rgb[2]}m"


def _lighten(rgb, amount=0.45):
    """Blend an RGB tuple toward white by `amount` (0=unchanged, 1=white)."""
    return tuple(int(c + (255 - c) * amount) for c in rgb)


def _blend(a, b, t):
    """Blend RGB `a` toward RGB `b` by `t` (0=a, 1=b). Used to sink the
    static dot field most of the way to the bar's dark background so the
    resting field reads as faint distant stars, not a gray smear."""
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


# Particle tunables. ONE star field that twinkles in place:
#  • a STATIC field fixes WHERE the stars are — fixed cells, never moving; each
#    is a small STAR glyph (not a period), sunk near the background. SPARSE
#    (~1 cell in 4) and NEVER two in a row — a run collapses to its first cell
#    so the field never shows a mechanical `⋆⋆` pair;
#  • TWINKLE happens only at those fixed cells: a star flares bright (⋆→✦/✧)
#    1 tick in `_STAR_RARITY`, then rests. Bare sky never spawns a transient
#    star, so a bright flash always lands ON a dot — never beside it.
# Stars are the fill hue lightened; the filled color is never changed.
# The status line ticks ~1Hz, so with a sparse field this lands a flare every
# few seconds at irregular intervals — a calm twinkle, NOT a flash every second.
_STAR_RARITY = 6            # a star at a dot cell flares bright ~1 tick in N
_DOT_DENSITY = 4            # ~1 empty cell in N carries a static dot (rest = sky)
_DOT_SEED = 0x5bd1e995      # fixed seed → the dot field is phase-independent
_SPARKLE_GLINT = 0.82       # star colour = fill hue lightened this much
_DOT_SINK = 0.62            # how far the faint dot tier sinks toward background
_DOT_GLYPHS = ("⋆",)        # faint star glyph for the resting field (star-shaped, not a period)
_STAR_GLYPHS = ("✦", "✧")

# Fill gradient: SAME-HUE ramp across the filled cells, anchored at the LEFT —
# the first cell is the EXACT severity colour (the identity anchor, always
# visible), fading darker toward the progress tip by scaling toward BLACK so
# the hue stays rich. Never fade toward the grey bar background: a
# grey-blended end is hard to tell from the empty cells (the bar reads
# reversed/half-empty) and the hue goes muddy (live feedback 2026-06-12).
# The darkened leading edge melts softly into the dark empty section while
# staying clearly tinted. A lone filled cell stays pure colour. 0.45 made the
# tip's luminance land too close to the empty grey (boundary went mushy at
# high fill in small fonts); 0.35 keeps the fade visible with a crisper edge.
_FILL_FADE = 0.35


def _sparkle_hash(i, phase):
    """Deterministic mixing hash of (cell index, render phase) → uint32.
    Cheap integer avalanche so adjacent cells/ticks scatter rather than march."""
    h = (i * 374761393 + phase * 668265263) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    return (h ^ (h >> 16)) & 0xFFFFFFFF


def _field_seed(label):
    """Deterministic per-bar seed from its label ("5h", "7d", …) so each bar
    gets its OWN star arrangement — without it, every width-10 bar shares the
    identical field and two side-by-side bars look like mirror-image skies."""
    return _sparkle_hash(sum(ord(c) for c in label), 0xA5A5)


def _is_dot_cell(i, seed=0):
    """Whether cell `i` is a static-dot candidate (before adjacency thinning).
    Phase-independent → the field never moves. `seed` shifts the arrangement
    per bar so the 5h and 7d skies differ."""
    return _sparkle_hash(i, _DOT_SEED + seed) % _DOT_DENSITY == 0


def _static_dot(i, seed=0):
    """Faint star glyph for the STATIC background field at cell `i`, or None
    for blank sky. Sparse (~1 cell in `_DOT_DENSITY`) and NEVER adjacent: when
    a candidate's left neighbour is also a candidate we drop this one, so a run
    collapses to its first cell and the field can't show a mechanical `⋆⋆`
    pair. Mostly dark sky with the occasional faint star behind the twinkle.
    `seed` gives each bar a distinct arrangement."""
    if not _is_dot_cell(i, seed) or (i > 0 and _is_dot_cell(i - 1, seed)):
        return None
    return _DOT_GLYPHS[_sparkle_hash(i, _DOT_SEED + seed) % len(_DOT_GLYPHS)]


def _dot_is_bright(i, seed=0):
    """Two brightness tiers for the static field → near/far star depth."""
    return bool((_sparkle_hash(i, _DOT_SEED + seed) >> 6) & 1)


def normalize_thresholds(warning_threshold=None, critical_threshold=None):
    warning = DEFAULT_WARNING_THRESHOLD if warning_threshold is None else float(warning_threshold)
    critical = DEFAULT_CRITICAL_THRESHOLD if critical_threshold is None else float(critical_threshold)
    if not 0 <= warning < critical <= 100:
        raise ValueError("Thresholds must satisfy 0 <= warning < critical <= 100.")
    return warning, critical


def build_bar(percent, width=10):
    clamped = max(0.0, min(percent, 100.0))
    filled = int(clamped / 100 * width + 0.5)
    if percent > 0 and filled == 0:
        filled = 1
    return FILL * filled + EMPTY * (width - filled)


def color_for_percent(percent, theme=None, warning_threshold=None, critical_threshold=None):
    theme = theme or get_theme("graphite")
    warning, critical = normalize_thresholds(warning_threshold, critical_threshold)
    if percent >= critical:
        return _fg(theme.s_hot)
    if percent >= warning:
        return _fg(theme.s_warn)
    return _fg(theme.s_ok)


def bg_for_percent(percent, theme=None, warning_threshold=None, critical_threshold=None):
    theme = theme or get_theme("graphite")
    warning, critical = normalize_thresholds(warning_threshold, critical_threshold)
    if percent >= critical:
        return _bg(theme.s_hot)
    if percent >= warning:
        return _bg(theme.s_warn)
    return _bg(theme.s_ok)


def projection_pct(chip):
    """Numeric percent out of a `→NN%` projection chip.

    `→96%` → 96.0. Returns None when there's no usable projection: empty
    string, the `→--` placeholder, or anything unparseable. The chip is clamped
    to 0–100 upstream, so a projection that would blow past the cap arrives here
    as 100.0 — exactly the red-line value.
    """
    if not chip:
        return None
    # `→100%·1h12m` carries a depletion ETA after the percent — match the
    # leading number instead of assuming the chip ends at `%`.
    import re
    m = re.match(r"→?\s*(\d+(?:\.\d+)?)%", chip)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def window_severity_rgb(current_pct, projection_chip, theme=None,
                        warning_threshold=None, critical_threshold=None):
    """Severity RGB for a rate-limit window (5h / 7d).

    The projection drives the color when one is available — measured against
    the cap (warn 80 / crit 100) so the window reflects where usage is HEADED.
    With no projection yet (early in the window, `→--`) it falls back to the
    current usage on the configured comfort thresholds — `now`-semantics, the
    unchanged legacy behavior. Returns an (r, g, b) tuple, or None when there is
    nothing to color (no projection and no current usage).
    """
    theme = theme or get_theme("graphite")
    proj = projection_pct(projection_chip)
    if proj is not None:
        pct, warning, critical = (proj, PROJECTION_WARNING_THRESHOLD,
                                  PROJECTION_CRITICAL_THRESHOLD)
    elif current_pct is not None:
        pct = current_pct
        warning, critical = normalize_thresholds(warning_threshold,
                                                 critical_threshold)
    else:
        return None
    if pct >= critical:
        return theme.s_hot
    if pct >= warning:
        return theme.s_warn
    return theme.s_ok


def colorize(text, color, use_color=True):
    if not use_color:
        return text
    return f"{color}{text}{RESET}"


def build_battery_bar(percent, width=10, use_color=True, theme=None,
                      warning_threshold=None, critical_threshold=None,
                      shimmer_phase=None, seed=0, fill_rgb=None):
    theme = theme or get_theme("graphite")
    clamped = max(0.0, min(percent, 100.0))
    filled = int(clamped / 100 * width + 0.5)
    if percent > 0 and filled == 0:
        filled = 1
    text = "MAX" if percent > 100 else f"{percent:.0f}%"
    padded = text.center(width)
    if not use_color:
        result = ""
        for i, ch in enumerate(padded):
            if ch == " ":
                result += FILL if i < filled else EMPTY
            else:
                result += ch
        return result
    if fill_rgb is None:
        warning, critical = normalize_thresholds(warning_threshold, critical_threshold)
        fill_rgb = (theme.s_hot if percent >= critical
                    else theme.s_warn if percent >= warning else theme.s_ok)
    fill_dark = _blend(fill_rgb, (0, 0, 0), _FILL_FADE)
    bg_empty = _bg(theme.edge)
    fg_overlay = _fg(theme.pill_ink)
    # Optional particles (opt-in) in the EMPTY space: a static faint dot field
    # (never moves) overlaid with bright stars that twinkle in/out per tick.
    # The filled color is untouched — particles only occupy blank empty cells.
    star = _fg(_lighten(fill_rgb, _SPARKLE_GLINT))
    # Two depth tiers, both sunk toward the dark bar background so the resting
    # field whispers rather than smudges: `dim` is a far/faint star almost on
    # the background, `dim_bright` a nearer one at plain mute.
    dim = _fg(_blend(theme.mute, theme.edge, _DOT_SINK))
    dim_bright = _fg(theme.mute)
    result = ""
    for i, ch in enumerate(padded):
        if i < filled:
            t = i / (filled - 1) if filled > 1 else 0.0
            result += f"{_bg(_blend(fill_rgb, fill_dark, t))}{fg_overlay}{ch}"
        elif shimmer_phase is not None and ch == " ":
            dot = _static_dot(i, seed)
            if dot is None:
                # Blank sky — stays empty. A star NEVER spawns in a bare cell;
                # twinkling only happens where a star already lives, so the
                # bright flash always lands ON a dot, not beside it.
                result += f"{bg_empty}{fg_overlay} "
            elif _sparkle_hash(i, shimmer_phase + seed) % _STAR_RARITY == 0:
                # This star flares bright IN PLACE — same cell as its resting
                # dot — blooming from ⋆ to a brighter ✦/✧ for this tick.
                h = _sparkle_hash(i, shimmer_phase + seed)
                result += f"{bg_empty}{star}{_STAR_GLYPHS[(h >> 4) & 1]}"
            else:
                dcol = dim_bright if _dot_is_bright(i, seed) else dim
                result += f"{bg_empty}{dcol}{dot}"          # resting faint star
        else:
            result += f"{bg_empty}{fg_overlay}{ch}"
    result += RESET
    return result


def _build_dimension(label, pct, severity_color, use_color,
                     warning_threshold, critical_threshold, theme,
                     shimmer_phase=None, fill_rgb=None):
    mute = _fg(theme.mute)
    if pct is not None:
        bar = build_battery_bar(pct, use_color=use_color, theme=theme,
                                warning_threshold=warning_threshold,
                                critical_threshold=critical_threshold,
                                shimmer_phase=shimmer_phase,
                                seed=_field_seed(label),
                                fill_rgb=fill_rgb)
    else:
        if use_color:
            bar = f"{_bg(theme.edge)}{_fg(theme.pill_ink)}" + "--%".center(10) + RESET
        else:
            bar = EMPTY * 3 + "--%" + EMPTY * 4
    return (
        colorize(label, severity_color, use_color)
        + colorize("[", mute, use_color)
        + bar
        + colorize("]", mute, use_color)
    )


# ── language-segment helpers ──

_LANGUAGE_OVERRIDES = {"Chinese": "ZH", "Japanese": "JA"}


def _language_code(language):
    return _LANGUAGE_OVERRIDES.get(language, language[:2].upper())


def _language_trend(estimates):
    if not isinstance(estimates, list) or len(estimates) < 2:
        return "→"
    try:
        previous = float(estimates[-2].get("band"))
        current = float(estimates[-1].get("band"))
    except (AttributeError, TypeError, ValueError):
        return "→"
    if current > previous:
        return "↑"
    if current < previous:
        return "↓"
    return "→"


def _coach_enabled(config_path="~/.claude/language-coach.json"):
    try:
        cfg = json.loads(Path(config_path).expanduser().read_text(encoding="utf-8"))
        return bool(cfg.get("enabled", False))
    except (OSError, json.JSONDecodeError, ValueError):
        return False


MAX_LANGUAGES = 4


def format_language_body(progress_path):
    if not _coach_enabled():
        return ""
    path = Path(progress_path).expanduser()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    parts = []
    for language in sorted(payload):
        entry = payload.get(language)
        if not isinstance(entry, dict):
            continue
        current_band = entry.get("currentBand")
        if not isinstance(current_band, str) or not current_band:
            continue
        trend = _language_trend(entry.get("estimates"))
        parts.append(f"{_language_code(str(language))}:{current_band}{trend}")
        if len(parts) >= MAX_LANGUAGES:
            break
    return " ".join(parts)


def format_language_segment(progress_path, use_color=True, theme=None):
    body = format_language_body(progress_path)
    if not body:
        return ""
    theme = theme or get_theme("graphite")
    return colorize(f"📚 {body}", _fg(theme.s_ok), use_color)


def _forecast_color(chip: str, theme):
    """hot when ≤10 min (bare seconds, or '~Nm' with N≤10), else warn."""
    body = chip.lstrip("~")
    if "h" in body:
        return _fg(theme.s_warn)
    if body.endswith("s"):
        return _fg(theme.s_hot)
    if body.endswith("m"):
        try:
            return _fg(theme.s_hot if int(body[:-1]) <= 10 else theme.s_warn)
        except ValueError:
            return _fg(theme.s_warn)
    return _fg(theme.s_warn)


def _projection_color(chip: str, theme):
    """`→NN%` end-of-window projection chip: hot ≥85%, warn ≥70%, else muted —
    the same red/yellow lines the window bar uses (window_severity_rgb), so the
    chip and the bar it sits next to never disagree. Below the warn line the
    chip stays muted (an unalarming projection), where the bar goes green.
    `→--` (not computable yet) is muted."""
    body = chip.lstrip("→").rstrip("%")
    try:
        v = int(body)
    except ValueError:
        return _fg(theme.mute)
    if v >= PROJECTION_CRITICAL_THRESHOLD:
        return _fg(theme.s_hot)
    if v >= PROJECTION_WARNING_THRESHOLD:
        return _fg(theme.s_warn)
    return _fg(theme.mute)


def _render_forecast(chip: str, theme, use_color: bool) -> str:
    """Style a forecast chip. `~<eta>` (imminent, ≤1h to the cap) → a ⚠ +
    urgency-colored countdown. `→NN%` (projected end-of-window usage) → colored
    by how close to the cap it projects (muted / warn / hot), glyph-free: it's a
    projection, not an alarm."""
    if chip.startswith("~"):
        return colorize(f"⚠{chip}", _forecast_color(chip, theme), use_color)
    return colorize(chip, _projection_color(chip, theme), use_color)


def _render_projection(chip: str, theme, use_color: bool) -> str:
    return colorize(chip, _projection_color(chip, theme), use_color)


def get_countdown_emoji(minutes_to_reset):
    if minutes_to_reset is None:
        return ""
    if minutes_to_reset <= 1:
        return " \U0001f389"
    if minutes_to_reset <= 10:
        return " ✨"
    if minutes_to_reset <= 30:
        return " ⚡"
    return ""


def _format_model(model, severity_color, mute_color, use_color):
    """Render `Opus 4.7(280.0k/1.0M)` with the parens muted and the rest
    in severity_color. Falls back to a single-color render when no parens.

    Anchors to the LAST `(...)` group so model names that already contain
    parens (e.g. `Opus(beta) 4.7(280k/1M)`) get their context bracket
    muted, not the version annotation. The greedy `.*` swallows everything
    up to the last paren group; the non-greedy `.*?` tail then matches
    whatever (usually nothing) follows it.
    """
    m = re.match(r"^(.*)(\([^)]*\))(.*?)$", model)
    if not m:
        return colorize(model, severity_color, use_color)
    name, parens, tail = m.groups()
    inner = parens[1:-1]
    return (
        colorize(name, severity_color, use_color)
        + colorize("(", mute_color, use_color)
        + colorize(inner, severity_color, use_color)
        + colorize(")", mute_color, use_color)
        + colorize(tail, severity_color, use_color)
    )


def format_status_line(
    msgs_pct, tkns_pct, reset_time, model,
    weekly_pct=None, reset_time_7d="",
    ctx_pct=None,
    bypass=False, use_color=True,
    countdown_emoji="",
    warning_threshold=None, critical_threshold=None,
    lang_text="", cost_text="",
    theme=None,
    shimmer_phase=None,
    projection_5h: str = "",
    projection_7d: str = "",
    forecast_5h: str = "",
    forecast_7d: str = "",
    no_quota: bool = False,
    balance_text="",
    balance_pct=None,
    balance_amount="",
    quota_stale: bool = False,
):
    """Build the complete classic-style status line.

    Each numeric segment colors itself: 5h by msgs_pct, 7d by weekly_pct,
    model by ctx_pct (None => neutral theme.ink). Separator and brackets
    use theme.mute. (used/size) parens muted, numbers stay severity.

    When ``no_quota`` is True (third-party relay / Bedrock / Vertex — no official
    5h/7d quota), the two quota bars are dropped and the context window is
    promoted to its own ``ctx[…]`` battery bar instead (claude-hud-style),
    followed by the model name. The activity tail is appended by styles.render.
    """
    theme = theme or get_theme("graphite")
    warning_threshold, critical_threshold = normalize_thresholds(
        warning_threshold, critical_threshold
    )
    mute = _fg(theme.mute)
    ink = _fg(theme.ink)

    if no_quota:
        if ctx_pct is None:
            ctx_fill_rgb = None
            ctx_color = mute
        else:
            ctx_fill_rgb = (
                theme.s_hot if ctx_pct >= CONTEXT_CRITICAL_THRESHOLD
                else theme.s_warn if ctx_pct >= CONTEXT_WARNING_THRESHOLD
                else theme.s_ok
            )
            ctx_color = _fg(ctx_fill_rgb)
        dim_ctx = _build_dimension(
            "ctx", ctx_pct, ctx_color, use_color,
            CONTEXT_WARNING_THRESHOLD, CONTEXT_CRITICAL_THRESHOLD, theme,
            shimmer_phase=shimmer_phase, fill_rgb=ctx_fill_rgb,
        )
        parts = [dim_ctx]
        # Model carries neutral ink: the ctx bar already conveys severity, and
        # the (used/size) suffix is dropped upstream since the bar IS the readout.
        parts.append(_format_model(model, ink, mute, use_color))
        # Relay balance is the headline number in no-quota mode (it's the
        # closest thing to "quota left"), so it sits right after the model,
        # ahead of the session cost. When a remaining % is available it renders
        # as a fuel-gauge battery (fill = remaining, green when full → red when
        # nearly empty); otherwise it falls back to the plain `bal $X` text.
        if balance_pct is not None:
            fill = _balance_fill_rgb(balance_pct, theme)
            bar = _build_dimension(
                "bal", balance_pct, _fg(fill), use_color,
                BALANCE_LOW_THRESHOLD, BALANCE_CRITICAL_THRESHOLD, theme,
                fill_rgb=fill,
            )
            seg = bar
            if balance_amount:
                seg += " " + colorize(balance_amount, _fg(fill), use_color)
            parts.append(seg)
        elif balance_text:
            parts.append(colorize(balance_text, _fg(theme.s_ok), use_color))
        if cost_text:
            parts.append(colorize(f"$ {cost_text}", ink, use_color))
        if lang_text:
            parts.append(lang_text)
        if bypass:
            parts.append(colorize("⚠️BYPASS", _fg(theme.s_hot), use_color))
        separator = colorize(" | ", mute, use_color)
        return separator.join(parts)

    if quota_stale and msgs_pct is None and weekly_pct is None:
        # The quota cache rotted (no fresh tick for a while — displaced
        # statusLine / dead daemon). Two blank `--%` bars read as "broken"; an
        # explicit, actionable hint tells the user it's stale and a restart
        # refreshes it (the diagnosis a Pro user otherwise had to dig for).
        parts = [colorize("⟳ 5h/7d stale·restart", _fg(theme.s_warn), use_color)]
        if ctx_pct is None:
            model_color = ink
        else:
            model_color = color_for_percent(
                ctx_pct, theme=theme,
                warning_threshold=CONTEXT_WARNING_THRESHOLD,
                critical_threshold=CONTEXT_CRITICAL_THRESHOLD,
            )
        parts.append(_format_model(model, model_color, mute, use_color))
        if cost_text:
            parts.append(colorize(f"$ {cost_text}", ink, use_color))
        if lang_text:
            parts.append(lang_text)
        if bypass:
            parts.append(colorize("⚠️BYPASS", _fg(theme.s_hot), use_color))
        separator = colorize(" | ", mute, use_color)
        return separator.join(parts)

    # 5h/7d severity follows the projection (where usage is HEADED), falling
    # back to current usage before a projection exists. The bar fill LENGTH and
    # the printed % still reflect current usage — only the color is projected.
    rgb_5h = window_severity_rgb(msgs_pct, projection_5h, theme,
                                 warning_threshold, critical_threshold)
    rgb_7d = window_severity_rgb(weekly_pct, projection_7d, theme,
                                 warning_threshold, critical_threshold)
    color_5h = _fg(rgb_5h) if rgb_5h is not None else mute
    color_7d = _fg(rgb_7d) if rgb_7d is not None else mute

    dim_5h = _build_dimension("5h", msgs_pct, color_5h, use_color,
                              warning_threshold, critical_threshold, theme,
                              shimmer_phase=shimmer_phase, fill_rgb=rgb_5h)
    dim_5h += colorize(f"⏰{reset_time}{countdown_emoji}", color_5h, use_color)
    if projection_5h:
        dim_5h += " " + _render_projection(projection_5h, theme, use_color)
    if forecast_5h:
        dim_5h += " " + _render_forecast(forecast_5h, theme, use_color)
    parts = [dim_5h]

    dim_7d = _build_dimension("7d", weekly_pct, color_7d, use_color,
                              warning_threshold, critical_threshold, theme,
                              shimmer_phase=shimmer_phase, fill_rgb=rgb_7d)
    if reset_time_7d:
        dim_7d += colorize(f"⏰{reset_time_7d}", color_7d, use_color)
    if projection_7d:
        dim_7d += " " + _render_projection(projection_7d, theme, use_color)
    if forecast_7d:
        dim_7d += " " + _render_forecast(forecast_7d, theme, use_color)
    parts.append(dim_7d)

    if ctx_pct is None:
        model_color = ink
    else:
        # The model name reflects context-window fill, so it must use the
        # context band (70/85), NOT the 5h/7d comfort band — otherwise ~35%
        # context paints the model name yellow here while the identical 35%
        # reads green on the no-quota ctx bar. Same metric, one threshold.
        model_color = color_for_percent(
            ctx_pct, theme=theme,
            warning_threshold=CONTEXT_WARNING_THRESHOLD,
            critical_threshold=CONTEXT_CRITICAL_THRESHOLD,
        )
    parts.append(_format_model(model, model_color, mute, use_color))

    if cost_text:
        parts.append(colorize(f"$ {cost_text}", ink, use_color))
    if lang_text:
        parts.append(lang_text)
    if bypass:
        parts.append(colorize("⚠️BYPASS", _fg(theme.s_hot), use_color))

    separator = colorize(" | ", mute, use_color)
    return separator.join(parts)
