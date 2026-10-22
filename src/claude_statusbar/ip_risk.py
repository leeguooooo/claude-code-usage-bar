"""Opt-in network observations from background probes.

Render reads cached evidence only. Cheap exit checks run at most once per
minute; IP enrichment is cached for 30 minutes. A probe measures its own
route, not necessarily Claude's, and never establishes account status.
"""
import json
import math
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# Risk enrichment cadence; cheap exit checks are separate.
IP_RISK_TTL_S = 30 * 60.0
# Egress-IP re-verify cadence (ipify plus opt-in family probes). The daemon also runs this on its own heartbeat (see
# daemon.py), so a VPN toggle reflects even while you're idle and Claude Code
# isn't re-rendering the statusline.
IP_CHECK_TTL_S = 60.0
# A failed probe retries sooner, but not so fast that a dead network loops.
FAIL_RETRY_S = 5 * 60.0
# Inflight marker older than this is a crashed prober — allow a new spawn.
INFLIGHT_EXPIRY_S = 60.0
# proxycheck.io's documented bands: 0-33 clean, 34-66 suspicious, 67+ bad.
WARN_RISK = 34
CRIT_RISK = 67
# The warning line only appears above this risk score (user rule: a clean
# IP earns silence, not a green checkmark taking up a whole line).
SHOW_THRESHOLD = 40


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
    """Whether the proxycheck RISK reading is still current (ts vs its TTL).
    Used by the prober to decide if it can skip the proxycheck call."""
    if not isinstance(entry, dict):
        return False
    if now is None:
        now = time.time()
    try:
        age = now - float(entry.get("ts", 0))
    except (TypeError, ValueError, OverflowError):
        return False
    return math.isfinite(age) and -5 <= age < (IP_RISK_TTL_S if entry.get("ok") else FAIL_RETRY_S)


def should_refresh(entry: Optional[Dict[str, Any]], now: Optional[float] = None) -> bool:
    """Whether to spawn the prober. Gated on the cheap egress-IP CHECK cadence
    (``checked_ts``), not the risk TTL — so a VPN toggle is noticed within
    IP_CHECK_TTL_S even though proxycheck itself is re-run far less often."""
    if not isinstance(entry, dict):
        return True
    if now is None:
        now = time.time()
    if not entry.get("ok"):
        return is_fresh(entry, now) is False   # failed → FAIL_RETRY_S backoff
    checked = entry.get("checked_ts", entry.get("ts", 0))
    try:
        age = now - float(checked)
        return not math.isfinite(age) or age < -5 or age >= IP_CHECK_TTL_S
    except (TypeError, ValueError, OverflowError):
        return True


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


def _family_finding(entry: Dict[str, Any]) -> Tuple[str, str]:
    """Probe observations only; neither differing geo nor a clean probe proves
    the route of an actual Claude request."""
    from .ip_score import region_status
    # Primary enrichment remains useful when direct family probes are skipped.
    if region_status(entry.get("country")) in ("unsupported", "sanctioned"):
        return (f"✗ IP probe exit in {entry.get('country')} — unsupported region for Claude\n"
                "   ↳ actual Claude route unverified; details: cs doctor"), "crit"
    fam = entry.get("families")
    if not isinstance(fam, dict):
        return "", "ok"
    seen = [(name, fam.get(key)) for name, key in (("IPv6", "v6"), ("IPv4", "v4"))
            if isinstance(fam.get(key), dict)]
    for name, t in seen:
        if t.get("warp") not in (None, "off"):
            return (f"✗ {name} probe exit is Cloudflare WARP — VPN exit\n"
                    "   ↳ review network before signing in; details: cs doctor"), "crit"
    for name, t in seen:
        if region_status(t.get("loc")) in ("unsupported", "sanctioned"):
            return (f"✗ {name} probe exit in {t.get('loc')} — unsupported region for Claude\n"
                    "   ↳ actual Claude route unverified; details: cs doctor"), "crit"
    for name, t in seen:
        if t.get("verdict") == "ban-risk":
            kind = f" ({t['type']})" if t.get("type") else ""
            return (f"✗ {name} exit {t.get('ip')}{kind} — network risk signal\n"
                    "   ↳ review network before signing in; details: cs doctor"), "crit"
    v4, v6 = fam.get("v4"), fam.get("v6")
    if (isinstance(v4, dict) and isinstance(v6, dict) and v4.get("loc") and v6.get("loc")
            and v4["loc"] != v6["loc"]):
        return (f"⚠ ip exits differ: IPv4 {v4['loc']} / IPv6 {v6['loc']}\n"
                "   ↳ geolocation differs; Claude route unverified (cs doctor)"), "warn"
    return "", "ok"


def family_issue(entry: Dict[str, Any]) -> str:
    return _family_finding(entry)[0]


def _score(entry: Dict[str, Any]) -> int:
    try:
        return int(entry.get("risk", 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def risk_level(entry: Dict[str, Any]) -> str:
    family_level = _family_finding(entry)[1]
    risk = _score(entry)
    if family_level == "crit" or risk >= CRIT_RISK:
        return "crit"
    if family_level == "warn" or risk >= WARN_RISK or str(entry.get("proxy", "")).lower() == "yes":
        return "warn"
    return "ok"


def line_text(entry: Dict[str, Any]) -> str:
    """Two-line observation/action. No account prediction or routing assertion."""
    issue, family_level = _family_finding(entry)
    risk = _score(entry)
    if issue and (family_level == "crit" or risk < CRIT_RISK):
        return issue
    if risk <= SHOW_THRESHOLD:
        return ""
    kind = str(entry.get("type", "") or "").strip()
    kind_part = f" ({kind})" if kind else ""
    symbol = "✗" if risk >= CRIT_RISK else "⚠"
    return (f"{symbol} ip risk {risk}/100{kind_part} — network signal\n"
            "   ↳ review network before signing in; details: cs doctor")


def _checked_recently(entry: Dict[str, Any], now: float) -> bool:
    try:
        timestamp = float(entry.get("checked_ts", entry.get("ts", 0)))
        age = now - timestamp
        return math.isfinite(timestamp) and -5 <= age < IP_CHECK_TTL_S * 2
    except (TypeError, ValueError, OverflowError):
        return False


def cache_state(entry=None, now=None) -> str:
    """Machine-readable coverage state, without exposing cache values."""
    if not isinstance(entry, dict):
        return "unknown"
    if not entry.get("ok"):
        return "failed"
    try:
        risk = entry["risk"]
        if isinstance(risk, bool) or not math.isfinite(float(risk)) or not 0 <= float(risk) <= 100:
            return "unknown"
    except (KeyError, TypeError, ValueError, OverflowError):
        return "unknown"
    return "current" if _checked_recently(entry, time.time() if now is None else now) else "stale"


def cached_status(entry=None, now=None) -> Tuple[str, str]:
    """Pure rendering shared with doctor; never probes or starts a scanner."""
    if now is None:
        now = time.time()
    unknown = ("⚠ ip check unavailable — network status unknown\n"
               "   ↳ no account status inferred; details: cs doctor", "warn")
    state = cache_state(entry, now)
    if state == "unknown":
        return unknown
    if state == "current":
        return line_text(entry), risk_level(entry)
    previous = entry if entry.get("ok") else entry.get("last_good")
    if isinstance(previous, dict):
        text = line_text(previous)
        if text:
            first = text.split("\n", 1)[0]
            state = "refresh failed" if not entry.get("ok") else "check stale"
            return (first + f" (last known; {state})\n"
                    "   ↳ current status unknown; details: cs doctor"), risk_level(previous)
    return unknown


def ip_risk_line(*, spawn: bool = True) -> Tuple[str, str]:
    entry = read_cache()
    if spawn:
        ensure_fresh(entry)
    return cached_status(entry)


def ensure_fresh(entry=None) -> None:
    """Spawn the detached prober if the cache is due for a re-check and one
    isn't already running. Safe to call from anywhere (render path AND the
    daemon heartbeat) — the inflight marker prevents double-spawns. Never
    raises."""
    try:
        if entry is None:
            entry = read_cache()
        from . import identity
        if identity._BACKGROUND_COLLECTORS:
            if should_refresh(entry):
                from .refresh_pool import submit
                from ._ip_risk_refresh import main
                submit(('ip-risk',), main, False)
            return
        if should_refresh(entry) and not is_inflight():
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
    except Exception:
        pass
