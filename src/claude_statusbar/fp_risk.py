"""Local custom-endpoint notice, not a watermark or account-ban detector.

Configuration alone cannot establish which fields an installed Claude version
sends. No timezone-based severity, payload inspection or network request.
"""
import os
from ipaddress import ip_address
from pathlib import Path
from typing import Dict, Optional, Tuple

_OFFICIAL_API_HOST = "api.anthropic.com"


def _relay_host(env: Dict[str, str]) -> Optional[str]:
    """Remote relay host, or None for official, loopback, or unset URLs."""
    base = (env.get("ANTHROPIC_BASE_URL") or "").strip()
    if not base:
        return None
    from urllib.parse import urlparse
    parsed = urlparse(base if "//" in base else "//" + base)
    host = (parsed.hostname or "").strip().rstrip(".").lower()
    if not host or host == _OFFICIAL_API_HOST or host == "localhost":
        return None
    try:
        if ip_address(host).is_loopback:
            return None
    except ValueError:
        pass
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
    """Notice the configured remote endpoint without inferring client behavior.

    Loopback and absent settings stay silent, but that silence does not verify
    the upstream of a local gateway or imply account safety.
    """
    if env is None:
        env = os.environ
    f = fp_risk_finding(env)
    return (f.legacy, "warn") if f else ("", "ok")


def fp_risk_finding(env: Optional[Dict[str, str]] = None):
    """Status-line form of fp_risk_line: a `note`-level Finding or None."""
    from .risk_line import Finding
    if env is None:
        env = os.environ
    if _relay_host(env) is None:
        return None
    return Finding(
        "note", "api", "custom_endpoint", "metadata_unchecked", "check_telemetry",
        "⚠ custom API endpoint — request metadata not inspected\n"
        "   ↳ review endpoint and telemetry settings: cs doctor")
