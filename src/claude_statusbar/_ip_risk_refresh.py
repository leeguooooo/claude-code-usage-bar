"""Detached egress-IP risk prober — spawned by ip_risk.ensure_fresh().

Fully local: no call to our own Worker. Two tiers keep third-party load tiny:

  * cheap tier — ipify returns the egress IP (unlimited, ~no cost). Run every
    spawn to detect a VPN toggle fast.
  * full tier — only when the IP changed or the risk reading aged out: ONE call
    to ipapi.is (the user's OWN quota, distributed across users, ~1000/day
    each) for datacenter/vpn/proxy/tor/abuser + ASN + country, then local
    scoring (ip_score). So a fleet of statusbar users never concentrates load
    on any shared quota or on our Worker.

Every spawn also asks claude.ai itself which exit it sees, once over IPv4 and
once over IPv6 (``family_traces``). ipify is IPv4-only, but claude.ai is
dual-stack and clients prefer IPv6 — a proxy that only carries IPv4 leaves the
real IPv6 exposed while the IPv4 reading looks clean.

Never raises; a failure writes an ``ok: false`` entry so the render path backs
off for FAIL_RETRY_S instead of respawning every render.
"""
import json
import socket
import ssl
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

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


_TRACE_HOST = "claude.ai"
_TRACE_TIMEOUT_S = 4.0


def _trace_over(family: int) -> dict:
    """GET https://claude.ai/cdn-cgi/trace pinned to one address family →
    {"ip", "loc", "warp"}. Raw socket + TLS because urllib can't force a
    family; HTTP/1.0 so the body is never chunked."""
    addr = socket.getaddrinfo(_TRACE_HOST, 443, family, socket.SOCK_STREAM)[0][4]
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.settimeout(_TRACE_TIMEOUT_S)
    try:
        sock.connect(addr)
        ctx = ssl.create_default_context()
        with ctx.wrap_socket(sock, server_hostname=_TRACE_HOST) as tls:
            tls.sendall((f"GET /cdn-cgi/trace HTTP/1.0\r\nHost: {_TRACE_HOST}\r\n"
                         f"User-Agent: {_UA}\r\nConnection: close\r\n\r\n").encode())
            raw = b""
            while len(raw) < 16384:
                chunk = tls.recv(4096)
                if not chunk:
                    break
                raw += chunk
    finally:
        sock.close()
    return parse_trace(raw.decode("utf-8", "replace").partition("\r\n\r\n")[2])


def parse_trace(body: str) -> dict:
    kv = dict(line.split("=", 1) for line in body.splitlines() if "=" in line)
    if not kv.get("ip"):
        raise ValueError("no ip in trace")
    return {"ip": kv["ip"].strip(), "loc": (kv.get("loc") or "").strip().upper() or None,
            "warp": (kv.get("warp") or "").strip() or None}


def family_traces() -> dict:
    """{"v4": trace|None, "v6": trace|None}; a family that can't connect is
    simply absent (no IPv6 is normal). Skipped (empty) when an HTTPS proxy is
    configured in the environment: Claude Code would go through that proxy,
    which a raw socket doesn't, so the reading wouldn't be Claude's route."""
    if urllib.request.getproxies().get("https"):
        return {}

    def one(family):
        try:
            return _trace_over(family)
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        v4, v6 = pool.map(one, (socket.AF_INET, socket.AF_INET6))
    return {"v4": v4, "v6": v6}


def evaluate_ip() -> dict:
    """One ipapi.is self-check → local Claude-risk verdict."""
    raw = json.loads(_get("https://api.ipapi.is/"))
    ip = raw.get("ip")
    if not ip or not isinstance(ip, str):
        raise ValueError("no ip")
    asn = raw.get("asn") or {}
    company = raw.get("company") or {}
    loc = raw.get("location") or {}
    sig = {
        "is_datacenter": raw.get("is_datacenter"),
        "is_vpn": raw.get("is_vpn"),
        "is_proxy": raw.get("is_proxy"),
        "is_tor": raw.get("is_tor"),
        "is_abuser": raw.get("is_abuser"),
        "abuser_score": _parse_abuser(asn.get("abuser_score")),
        # org + ASN drive the China-cloud check (flagged by provider, not IP geo)
        "org": company.get("name") or asn.get("org") or asn.get("descr"),
        "asn": _parse_asn(asn.get("asn")),
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


def _parse_asn(v):
    """ipapi.is asn.asn may be an int or a string like 'AS12345' / '12345'."""
    if isinstance(v, int):
        return v
    import re
    m = re.search(r"(\d+)", str(v or ""))
    return int(m.group(1)) if m else 0


def main(force=True) -> int:
    from .git_cache import try_claim
    lock = try_claim('ip-risk')
    if lock is None:
        return 0
    try:
        if not force and not ip_risk.should_refresh(ip_risk.read_cache()):
            return 0
        return _refresh_locked()
    finally:
        lock.close()


def _refresh_locked() -> int:
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
    # Cheap (two tiny requests) and the IPv6 exit can change without the IPv4
    # one moving, so re-read it on every check, not only on the risk TTL.
    try:
        entry["families"] = family_traces()
    except Exception:
        entry.pop("families", None)
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
