"""Relay fingerprint-risk warning line (``show_fp_risk``).

Claude Code embeds a per-request identity mark in the system prompt's
"Today's date is …" sentence when ``ANTHROPIC_BASE_URL`` points off the
official host — one dimension of that mark is the system timezone (the date
separator flips to a slash for ``Asia/Shanghai`` / ``Asia/Urumqi``). That
mark rides in the outgoing request, which the status bar never sees or
touches, so this module does NOT detect or alter the mark. It only reads the
same local signals the user already controls — relay base URL + system
timezone — and surfaces "this setup is fingerprintable, ban risk" so the
user can make an informed call (the robust fix is the official endpoint).
"""
import os
from pathlib import Path
from typing import Dict, Optional, Tuple

_OFFICIAL_API_HOST = "api.anthropic.com"
# Timezones whose date separator the watermark flips (per the mechanism
# writeup) — the one dimension that's list-free and locally verifiable.
_MARKED_TIMEZONES = {"Asia/Shanghai", "Asia/Urumqi"}


def _relay_host(env: Dict[str, str]) -> Optional[str]:
    """The relay host when ANTHROPIC_BASE_URL points off the official API,
    else None (official / unset). Same host-parsing as no-quota detection."""
    base = (env.get("ANTHROPIC_BASE_URL") or "").strip()
    if not base:
        return None
    from urllib.parse import urlparse
    parsed = urlparse(base if "//" in base else "//" + base)
    host = (parsed.hostname or "").strip().rstrip(".").lower()
    if not host or host == _OFFICIAL_API_HOST:
        return None
    return host


def system_timezone() -> Optional[str]:
    """Best-effort IANA timezone name (matches what Claude Code reads via
    ``Intl…resolvedOptions().timeZone``). None when it can't be resolved."""
    tz = (os.environ.get("TZ") or "").strip()
    if "/" in tz:
        return tz
    try:
        # macOS / most Linux: /etc/localtime is a symlink into the tz db.
        target = os.readlink("/etc/localtime")
        marker = "zoneinfo/"
        if marker in target:
            return target.split(marker, 1)[1]
    except OSError:
        pass
    try:
        p = Path("/etc/timezone")
        if p.exists():
            name = p.read_text(encoding="utf-8").strip()
            if "/" in name:
                return name
    except OSError:
        pass
    return None


def fp_risk_line(env: Optional[Dict[str, str]] = None) -> Tuple[str, str]:
    """(text, level) for the dedicated warning line; ("", "ok") = hidden.

    Fires only when a relay is active AND the system timezone is one the
    watermark marks — the honest, list-free signal. Never touches the network
    or the outgoing request.
    """
    if env is None:
        env = os.environ
    host = _relay_host(env)
    if host is None:
        return "", "ok"
    tz = system_timezone()
    if tz in _MARKED_TIMEZONES:
        return ("⚠ relay + CN timezone — requests are fingerprintable, "
                "account-ban risk (official endpoint avoids it)"), "warn"
    return "", "ok"
