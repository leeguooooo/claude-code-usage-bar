"""Egress-IP risk segment (``show_ip_risk``).

Answers "how clean is the IP my traffic exits from right now?" — users on
relays/VPNs care because a dirty egress IP raises account-risk. Data source
is proxycheck.io's free tier (risk score 0-100 + proxy/VPN flag, no key
needed); the reference site the user compares against (ippure.com) hides its
API behind browser fingerprinting, so it can't back a CLI.

Same architecture as the relay-balance segment: the render path ONLY reads a
cache file; when the cache is stale a detached ``_ip_risk_refresh`` process
re-probes (two ~8s HTTP calls) and rewrites the cache. Nothing on the render
path ever touches the network. Probe cadence is IP_RISK_TTL_S (30 min) — the
user explicitly does not want per-render checking.
"""
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# Re-probe cadence for a successful reading.
IP_RISK_TTL_S = 30 * 60.0
# A failed probe retries sooner, but not so fast that a dead network loops.
FAIL_RETRY_S = 5 * 60.0
# Inflight marker older than this is a crashed prober — allow a new spawn.
INFLIGHT_EXPIRY_S = 60.0
# proxycheck.io's documented bands: 0-33 clean, 34-66 suspicious, 67+ bad.
WARN_RISK = 34
CRIT_RISK = 67


def _cache_root() -> Path:
    return Path(os.path.expanduser("~/.cache/claude-statusbar"))


def cache_path() -> Path:
    return _cache_root() / "ip_risk.json"


def _inflight_path() -> Path:
    return _cache_root() / "ip_risk.inflight"


def read_cache() -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(cache_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def write_cache_atomic(entry: Dict[str, Any]) -> None:
    from .cache import atomic_write_text
    try:
        atomic_write_text(cache_path(), json.dumps(entry))
    except OSError:
        pass


def is_fresh(entry: Optional[Dict[str, Any]], now: Optional[float] = None) -> bool:
    if not isinstance(entry, dict):
        return False
    if now is None:
        now = time.time()
    try:
        age = now - float(entry.get("ts", 0))
    except (TypeError, ValueError):
        return False
    return age < (IP_RISK_TTL_S if entry.get("ok") else FAIL_RETRY_S)


def is_inflight(now: Optional[float] = None) -> bool:
    try:
        mtime = _inflight_path().stat().st_mtime
    except OSError:
        return False
    if now is None:
        now = time.time()
    return (now - mtime) < INFLIGHT_EXPIRY_S


def mark_inflight() -> None:
    try:
        _inflight_path().write_text(str(time.time()), encoding="utf-8")
    except OSError:
        pass


def clear_inflight() -> None:
    try:
        _inflight_path().unlink()
    except OSError:
        pass


def risk_level(entry: Dict[str, Any]) -> str:
    """"ok" / "warn" / "crit" per proxycheck bands; a proxy/VPN verdict is at
    least warn even at a low score (the flag itself is the risk signal)."""
    try:
        risk = int(entry.get("risk", 0))
    except (TypeError, ValueError):
        risk = 0
    if risk >= CRIT_RISK:
        return "crit"
    if risk >= WARN_RISK or str(entry.get("proxy", "")).lower() == "yes":
        return "warn"
    return "ok"


def segment_text(entry: Dict[str, Any]) -> str:
    level = risk_level(entry)
    try:
        risk = int(entry.get("risk", 0))
    except (TypeError, ValueError):
        risk = 0
    if level == "ok":
        return "ip✓"
    mark = "⚠" if level == "warn" else "✗"
    return f"ip{mark}{risk}"


def ip_risk_segment(*, spawn: bool = True) -> Tuple[str, str]:
    """(text, level) for the identity line; ("", "ok") hides the segment.

    Fresh ok cache → render it. Stale → keep rendering the last good reading
    (risk doesn't flap minute-to-minute) while a detached refresh runs.
    Failed cache with nothing good to show → hidden.
    """
    entry = read_cache()
    fresh = is_fresh(entry)
    if not fresh and spawn and not is_inflight():
        mark_inflight()
        try:
            import subprocess
            import sys
            subprocess.Popen(
                [sys.executable, "-m", "claude_statusbar._ip_risk_refresh"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                start_new_session=True,
            )
        except (OSError, ValueError):
            clear_inflight()
    if isinstance(entry, dict) and entry.get("ok"):
        return segment_text(entry), risk_level(entry)
    return "", "ok"
