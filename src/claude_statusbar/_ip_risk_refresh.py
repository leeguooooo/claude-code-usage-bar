"""Detached egress-IP risk prober — spawned by ip_risk.ip_risk_segment().

One HTTP call to our own service ip-check.leeguoo.com (self-check: it reads
the caller's egress IP from the edge and returns the risk verdict in a single
response), then one atomic cache write. No third-party dependency, no rate
cap for our own users — the service's "self" quota bucket is sized for this
prober. Never raises; a failure writes an ``ok: false`` entry so the render
path backs off for FAIL_RETRY_S instead of respawning every render.
"""
import json
import sys
import time
import urllib.request

from . import ip_risk

_TIMEOUT_S = 8.0
_UA = "claude-statusbar (+https://github.com/leeguooooo/claude-code-usage-bar)"
# Self-check endpoint (no ?ip= → the generous, harvest-proof "self" quota
# bucket). Returns {ip, risk, level, type, reasons, ...}.
_SERVICE_URL = "https://ip-check.leeguoo.com/"


def _get(url: str, *, accept_json: bool = False) -> str:
    headers = {"User-Agent": _UA}
    if accept_json:
        headers["Accept"] = "application/json"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
        return resp.read().decode("utf-8", "replace")


def check_self() -> dict:
    """Query our service for THIS machine's egress-IP verdict (one call)."""
    raw = json.loads(_get(_SERVICE_URL, accept_json=True))
    ip = raw.get("ip")
    if not ip or not isinstance(ip, str):
        raise ValueError("no ip")
    typ = (raw.get("type") or "").strip()
    level = (raw.get("level") or "").strip()
    proxy = "yes" if (typ in ("vpn", "residential-proxy", "hosting", "tor")
                      or level in ("warn", "crit")) else "no"
    return {
        "ok": True,
        "ip": ip,
        "risk": int(raw.get("risk") or 0),
        "proxy": proxy,
        "type": typ,
        "provider": "ip-check.leeguoo.com",
    }


def main() -> int:
    now = time.time()
    prev = ip_risk.read_cache() or {}
    try:
        entry = check_self()
    except Exception:
        # Keep the last good reading around so the bar can keep showing it
        # while the network is flaky; only the freshness clock resets.
        entry = {"ok": False, "ts": now}
        if prev.get("ok"):
            entry["last_good"] = {k: prev.get(k) for k in
                                  ("ip", "risk", "proxy", "type")}
        entry["checked_ts"] = now
        try:
            ip_risk.write_cache_atomic(entry)
        finally:
            ip_risk.clear_inflight()
        return 0
    # Success: a full probe stamps a new risk ts; a short-circuit keeps the
    # old ts and only advances checked_ts.
    entry.setdefault("ts", now)
    entry["checked_ts"] = now
    try:
        ip_risk.write_cache_atomic(entry)
    finally:
        ip_risk.clear_inflight()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
