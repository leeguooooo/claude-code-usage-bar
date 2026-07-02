"""Detached egress-IP risk prober — spawned by ip_risk.ensure_fresh().

Fully local: no call to our own Worker. Two tiers keep third-party load tiny:

  * cheap tier — ipify returns the egress IP (unlimited, ~no cost). Run every
    spawn to detect a VPN toggle fast.
  * full tier — only when the IP changed or the risk reading aged out: ONE call
    to ipapi.is (the user's OWN quota, distributed across users, ~1000/day
    each) for datacenter/vpn/proxy/tor/abuser + ASN + country, then local
    scoring (ip_score). So a fleet of statusbar users never concentrates load
    on any shared quota or on our Worker.

Never raises; a failure writes an ``ok: false`` entry so the render path backs
off for FAIL_RETRY_S instead of respawning every render.
"""
import json
import sys
import time
import urllib.request

from . import ip_risk, ip_score

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


def evaluate_ip() -> dict:
    """One ipapi.is self-check → local Claude-risk verdict."""
    raw = json.loads(_get("https://api.ipapi.is/"))
    ip = raw.get("ip")
    if not ip or not isinstance(ip, str):
        raise ValueError("no ip")
    asn = raw.get("asn") or {}
    loc = raw.get("location") or {}
    sig = {
        "is_datacenter": raw.get("is_datacenter"),
        "is_vpn": raw.get("is_vpn"),
        "is_proxy": raw.get("is_proxy"),
        "is_tor": raw.get("is_tor"),
        "is_abuser": raw.get("is_abuser"),
        "abuser_score": _parse_abuser(asn.get("abuser_score")),
    }
    country = loc.get("country_code") or loc.get("country")
    out = ip_score.evaluate(sig, country)
    out.update({"ok": True, "ip": ip, "provider": "ipapi.is+local"})
    return out


def _parse_abuser(s):
    if isinstance(s, (int, float)):
        return float(s)
    import re
    m = re.search(r"([\d.]+)", str(s or ""))
    return float(m.group(1)) if m else None


def main() -> int:
    now = time.time()
    prev = ip_risk.read_cache() or {}
    try:
        ip = egress_ip()
        # Same egress and the risk reading is still fresh → skip the ipapi.is
        # call, just advance the cheap-check clock.
        if (prev.get("ok") and prev.get("ip") == ip
                and ip_risk.is_fresh(prev, now)):
            entry = dict(prev)
        else:
            entry = evaluate_ip()
    except Exception:
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
