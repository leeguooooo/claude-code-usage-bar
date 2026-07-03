"""Detached helper that probes a third-party relay's OpenAI-compatible billing
endpoints and writes the resulting balance to the balance cache. Spawned by the
inline render path (core.py) the same way ``_git_refresh`` is — fire-and-forget,
output discarded.

Contract:
  argv[1]                — the relay base URL (e.g. https://relay.example.com)
  env CS_BALANCE_KEY     — primary bearer token (ANTHROPIC_API_KEY)
  env CS_BALANCE_AUTH    — fallback bearer token (ANTHROPIC_AUTH_TOKEN)
  env CS_BALANCE_FP      — cache fingerprint (so we don't re-derive the key here)

It NEVER raises out to the shell: any failure (network, auth, 404, bad JSON)
is caught and recorded as ``supported=False`` so the bar simply hides the
segment and the negative cache keeps us from re-probing for an hour.

Balance math follows the OpenAI / new-api / one-api convention:
  total = subscription.hard_limit_usd     (USD)
  used  = usage.total_usage / 100         (total_usage is in cents)
  balance = total - used
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

from . import balance_cache


_TIMEOUT_S = 6
# Candidate path prefixes. Relays put the OpenAI billing shim under /v1 (most),
# at the root (some), or the base URL already ends in /v1. We try in order and
# take the first that returns usable JSON.
_PREFIXES = ("/v1/dashboard/billing", "/dashboard/billing")


def _get_json(url: str, token: str) -> dict | None:
    # A descriptive User-Agent is required: some relays (Cloudflare-fronted
    # gateways, new-api behind a WAF) 403 the default ``Python-urllib/x.y`` UA.
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {token}",
                      "Accept": "application/json",
                      "User-Agent": "claude-statusbar-balance/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
            if resp.status != 200:
                return None
            body = resp.read(65536)
        data = json.loads(body.decode("utf-8", "replace"))
        return data if isinstance(data, dict) else None
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        return None


def _probe(base: str, token: str) -> dict | None:
    """Return {balance,total,used,currency} for the first prefix that yields a
    valid subscription object, else None. ``usage`` is best-effort: a missing
    usage object just means used=0 (balance == granted limit)."""
    base = base.rstrip("/")
    for prefix in _PREFIXES:
        sub = _get_json(f"{base}{prefix}/subscription", token)
        if not sub:
            continue
        total = sub.get("hard_limit_usd")
        if total is None:
            total = sub.get("system_hard_limit_usd")
        if not isinstance(total, (int, float)):
            # Subscription object exists but carries no limit we understand —
            # try the next prefix rather than declaring support.
            continue
        usage = _get_json(f"{base}{prefix}/usage", token)
        used_cents = 0.0
        if isinstance(usage, dict) and isinstance(
                usage.get("total_usage"), (int, float)):
            used_cents = float(usage["total_usage"])
        used = used_cents / 100.0
        return {
            "balance": round(float(total) - used, 4),
            "total": float(total),
            "used": round(used, 4),
            "currency": "USD",
        }
    return None


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        return 0
    base = argv[1]
    fp = os.environ.get("CS_BALANCE_FP", "")
    if not fp:
        fp = balance_cache.fingerprint(
            base, os.environ.get("CS_BALANCE_KEY", "")
            or os.environ.get("CS_BALANCE_AUTH", ""))

    result = None
    for env_name in ("CS_BALANCE_KEY", "CS_BALANCE_AUTH"):
        token = os.environ.get(env_name, "")
        if not token:
            continue
        result = _probe(base, token)
        if result is not None:
            break

    try:
        if result is None:
            balance_cache.write_cache_atomic(
                fp, {"ts": time.time(), "supported": False})
        else:
            balance_cache.write_cache_atomic(
                fp, {"ts": time.time(), "supported": True, **result})
    finally:
        balance_cache.clear_inflight(fp)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except Exception:
        # Never crash a detached refresh — the bar degrades to "no balance".
        sys.exit(0)
