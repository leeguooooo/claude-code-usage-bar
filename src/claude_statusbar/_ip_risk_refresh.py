"""Detached egress-IP risk prober — spawned by ip_risk.ip_risk_segment().

Two HTTP calls (own egress IP via ipify, then proxycheck.io risk for that
IP), then one atomic cache write. Never raises; a failure writes an
``ok: false`` entry so the render path backs off for FAIL_RETRY_S instead of
respawning every render.
"""
import json
import sys
import time
import urllib.request

from . import ip_risk

_TIMEOUT_S = 8.0
_UA = "claude-statusbar (+https://github.com/leeguooooo/claude-code-usage-bar)"


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
        return resp.read().decode("utf-8", "replace")


def egress_ip() -> str:
    ip = _get("https://api.ipify.org").strip()
    if not ip or len(ip) > 64:
        raise ValueError("no ip")
    return ip


def risk_for(ip: str) -> dict:
    raw = json.loads(_get(f"https://proxycheck.io/v2/{ip}?risk=1&vpn=1"))
    info = raw.get(ip) if isinstance(raw, dict) else None
    if not isinstance(info, dict):
        raise ValueError("no info")
    return {
        "ok": True,
        "ip": ip,
        "risk": info.get("risk", 0),
        "proxy": info.get("proxy", ""),
        "type": info.get("type", ""),
        "provider": "proxycheck.io",
    }


def main() -> int:
    now = time.time()
    prev = ip_risk.read_cache() or {}
    try:
        ip = egress_ip()
        # Short-circuit: same egress IP and the risk reading is still within
        # its TTL → skip the rate-limited proxycheck call, just bump the
        # cheap-check clock so the render path stops re-spawning.
        if (prev.get("ok") and prev.get("ip") == ip
                and ip_risk.is_fresh(prev, now)):
            entry = dict(prev)
        else:
            entry = risk_for(ip)
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
