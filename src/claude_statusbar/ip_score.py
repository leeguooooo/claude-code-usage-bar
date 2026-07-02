"""Local IP → Claude-account-risk scoring, entirely in the plugin.

The prober calls ipapi.is directly (the caller's own quota, distributed across
users) and this module turns its flags into a risk score + Claude verdict — so
the statusbar never routes through our own Worker. It mirrors the scoring in
the ip-check.leeguoo.com service (classify.js + claude-verdict.js); the Worker
stays the public web/API/ranking surface, this is the self-contained path.

Weights are proxycheck.io's published baselines (datacenter 33 / VPN 50 /
Tor 75 / proxy 100); abuser tiers are ipapi.is's (>20% very-high … <0.05%
very-low). Region is the one officially-stated Anthropic trigger.
"""
from typing import Any, Dict, Optional, Tuple

# proxycheck.io category baselines.
_HOSTING, _VPN, _TOR, _PROXY = 33, 50, 75, 100

# Anthropic-blocked (US-sanctioned) and unsupported regions.
_SANCTIONED = {"KP", "IR", "CU", "SY", "RU", "BY"}
_UNSUPPORTED = {"CN", "HK"}
# Egress types that are high ban-risk for ANY Claude use (anonymizers). Plain
# datacenter is NOT here — API/Claude-Code from a cloud server is normal.
_BAN_TYPES = {"vpn", "proxy", "residential-proxy", "tor"}


def _abuser_points(score: Optional[float]) -> int:
    if not isinstance(score, (int, float)) or score <= 0:
        return 0
    if score > 0.20:
        return 40
    if score > 0.03:
        return 30
    if score > 0.0085:
        return 20
    if score > 0.0005:
        return 10
    return 0


def classify(sig: Dict[str, Any]) -> Dict[str, Any]:
    """sig = ipapi.is-shaped flags → {risk 0-100, type, level}."""
    datacenter = bool(sig.get("is_datacenter"))
    vpn = bool(sig.get("is_vpn"))
    proxy = bool(sig.get("is_proxy"))
    tor = bool(sig.get("is_tor"))
    abuser_score = sig.get("abuser_score")
    residential_proxy = proxy and not datacenter and not vpn

    risk = 0
    typ = "residential"
    if tor:
        risk += _TOR
        typ = "tor"
    if datacenter:
        risk += _HOSTING
        if typ == "residential":
            typ = "hosting"
    if vpn:
        risk += _VPN
        typ = "vpn/hosting" if typ == "hosting" else ("vpn" if typ == "residential" else typ)
    if residential_proxy:
        risk += _PROXY
        typ = "residential-proxy"
    elif proxy and not vpn:
        risk += _VPN
    risk += _abuser_points(abuser_score)
    risk = max(0, min(100, risk))
    level = "crit" if risk >= 70 else "warn" if risk >= 40 else "low" if risk >= 15 else "ok"
    return {"risk": risk, "type": typ, "level": level}


def verdict(risk: int, typ: str, country: Optional[str]) -> Dict[str, Any]:
    """Claude-account decision. Region first (the documented trigger), then
    anonymizer egress, then plain datacenter (a softer caution)."""
    cc = (country or "").upper()
    ip_is_ban = risk >= 67 or typ in _BAN_TYPES

    if cc in _SANCTIONED:
        return {"verdict": "ban-risk", "region": True}
    if cc in _UNSUPPORTED:
        return {"verdict": "ban-risk" if ip_is_ban else "caution", "region": True}
    if typ == "residential" and risk < 15:
        return {"verdict": "safe", "region": False}
    if ip_is_ban:
        return {"verdict": "ban-risk", "region": False}
    if typ == "hosting":
        return {"verdict": "caution", "region": False, "datacenter": True}
    return {"verdict": "caution", "region": False}


def score(risk: int, typ: str, country: Optional[str]) -> int:
    """Claude Safety Score, 0-100, higher = safer."""
    cc = (country or "").upper()
    s = 100 - int(risk or 0)
    if typ in _BAN_TYPES:
        s = min(s, 40)
    elif typ == "hosting":
        s = min(s, 60)
    if cc in _SANCTIONED:
        s = min(s, 5)
    elif cc in _UNSUPPORTED:
        s = min(s, 40)
    return max(0, min(100, s))


def evaluate(sig: Dict[str, Any], country: Optional[str]) -> Dict[str, Any]:
    """Full local verdict from ipapi.is signals. Returns the cache-entry shape
    the render path consumes (risk/type/proxy/verdict/score/region)."""
    c = classify(sig)
    v = verdict(c["risk"], c["type"], country)
    return {
        "risk": c["risk"],
        "type": c["type"],
        "level": c["level"],
        "proxy": "yes" if (c["type"] in _BAN_TYPES or c["type"] == "hosting"
                           or c["level"] in ("warn", "crit")) else "no",
        "verdict": v["verdict"],
        "region": v.get("region", False),
        "country": (country or "").upper() or None,
        "score": score(c["risk"], c["type"], country),
    }
