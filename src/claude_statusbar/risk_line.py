"""Structured network / endpoint findings and their one-line rendering.

A Finding carries the facts (`label value │ reason │ hint`) plus the legacy
two-line English text, which `cs doctor` and the plain-text paths still print
verbatim. The status line renders the structured form in one line, in the
user's language, coloring only the glyph, the value and the reason.
"""
from typing import NamedTuple, Optional

MESSAGES = {
    # reasons
    "unsupported_region": {"en": "unsupported region", "zh": "不支持的地区"},
    "vpn_exit":           {"en": "VPN exit", "zh": "VPN 出口"},
    "risk_signal":        {"en": "network risk signal", "zh": "网络风险信号"},
    "exits_differ":       {"en": "geolocation differs", "zh": "出口国家不同"},
    "risky_network":      {"en": "risky network", "zh": "网络有风险"},
    "check_unavailable":  {"en": "check unavailable", "zh": "检测不可用"},
    "metadata_unchecked": {"en": "metadata not inspected", "zh": "请求元数据未检查"},
    # hints
    "route_unverified":   {"en": "route unverified", "zh": "实际路线未验证"},
    "review_network":     {"en": "review before sign-in", "zh": "登录前先检查网络"},
    "status_unknown":     {"en": "status unknown", "zh": "状态未知"},
    "current_unknown":    {"en": "current status unknown", "zh": "当前状态未知"},
    "check_telemetry":    {"en": "check telemetry settings", "zh": "检查遥测设置"},
    # notes / values / labels
    "last_failed":        {"en": "last known; refresh failed", "zh": "上次结果；刷新失败"},
    "last_stale":         {"en": "last known; check stale", "zh": "上次结果；检测过期"},
    "custom_endpoint":    {"en": "custom endpoint", "zh": "自定义端点"},
    "exits":              {"en": "exits", "zh": "出口"},
}

GLYPH = {"crit": "✗", "warn": "⚠", "note": "◌"}


class Finding(NamedTuple):
    level: str            # crit | warn | note
    label: str            # IPv4 / IPv6 / ip / api / msg key
    value: str            # CN, WARP, 85/100 hosting, msg key …
    reason: str           # MESSAGES key
    hint: str             # MESSAGES key
    legacy: str           # exact two-line English text (doctor, no-color)
    note: Optional[str] = None   # MESSAGES key appended to the reason


def t(key: str, lang: str) -> str:
    entry = MESSAGES.get(key)
    if entry is None:
        return key          # literal (country code, IP, IPv6 …)
    return entry.get(lang) or entry["en"]


def format_finding(f: Finding, *, theme, lang: str = "en",
                   use_color: bool = True) -> str:
    """`✗ IPv6 CN │ unsupported region │ route unverified · cs doctor`."""
    reason = t(f.reason, lang)
    if f.note:
        reason += (f"（{t(f.note, lang)}）" if lang == "zh"
                   else f" ({t(f.note, lang)})")
    head = f"{GLYPH.get(f.level, '⚠')} {t(f.label, lang)}"
    value = t(f.value, lang)
    hint = t(f.hint, lang)
    if not use_color:
        lead = f"{head} {value}" if value else head
        return f"{lead} │ {reason} │ {hint} · cs doctor"
    from .styles import _fg, BOLD, RESET
    from .progress import _blend
    accent = {"crit": theme.s_hot, "warn": theme.s_warn}.get(
        f.level, _blend(theme.s_warn, theme.mute, 0.45))
    A, MUTE, EDGE = _fg(accent), _fg(theme.mute), _fg(theme.edge)
    sep = f"{EDGE} │ {RESET}"
    glyph = GLYPH.get(f.level, "⚠")
    lead = f"{A}{BOLD}{glyph}{RESET} {MUTE}{t(f.label, lang)}{RESET}"
    if value:
        lead += f" {A}{BOLD}{value}{RESET}"
    return (f"{lead}{sep}{A}{reason}{RESET}{sep}"
            f"{MUTE}{hint}{RESET} {EDGE}· cs doctor{RESET}")
