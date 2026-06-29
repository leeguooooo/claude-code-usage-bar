"""Tiny TTL cache for third-party-relay account balance, shared by the
inline render path and the detached ``_balance_refresh`` helper. Pure
stdlib; no top-level subprocess/urllib import so the render hot path stays
cheap when the cache is fresh.

Mirrors ``git_cache`` (read/is_fresh/write_atomic/inflight) but adds a
*negative* cache: a relay that doesn't expose the OpenAI-compatible billing
endpoints answers 404 forever, so once a probe comes back ``supported=False``
we stop re-probing for a long while instead of every few minutes.

Cache key is ``hash(base_url + ':' + key-fingerprint)`` — never the raw key —
so two accounts on the same relay (or the same account across relays) get
distinct buckets and can't bleed balances into each other.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Optional


# Balance changes slowly; a 5-minute positive TTL keeps the bar fresh without
# hammering the relay at the statusLine's ~1Hz refresh.
TTL_SECONDS = 300
# A relay that 404s the billing endpoints won't grow them mid-session — back
# off for an hour before re-probing rather than every 5 minutes.
NEGATIVE_TTL_SECONDS = 3600
# A spawned refresh that never writes (network hang killed by timeout) must not
# wedge the inflight gate forever.
INFLIGHT_MAX_AGE_S = 60


def _cache_root() -> Path:
    return Path(os.path.expanduser("~")) / ".cache" / "claude-statusbar" / "balance"


def fingerprint(base_url: str, key: str) -> str:
    """Stable per-(relay, key) bucket id. The raw key never touches disk."""
    h = hashlib.sha1()
    h.update((base_url or "").encode("utf-8"))
    h.update(b"\x00")
    h.update((key or "").encode("utf-8"))
    return h.hexdigest()


def cache_path_for(fp: str) -> Path:
    return _cache_root() / f"{fp}.json"


def read_cache(fp: str) -> Optional[dict]:
    try:
        return json.loads(cache_path_for(fp).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def is_fresh(entry: Optional[dict], now: Optional[float] = None) -> bool:
    """Fresh = within the TTL that matches the entry's polarity. An
    ``supported=False`` entry uses the long negative TTL; a real balance uses
    the short positive TTL."""
    if not entry:
        return False
    ts = entry.get("ts")
    if not isinstance(ts, (int, float)):
        return False
    ttl = TTL_SECONDS if entry.get("supported") else NEGATIVE_TTL_SECONDS
    return (now or time.time()) - ts < ttl


def write_cache_atomic(fp: str, entry: dict) -> None:
    p = cache_path_for(fp)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=f".{p.name}.",
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(entry))
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _inflight_path(fp: str) -> Path:
    return cache_path_for(fp).with_suffix(".inflight")


def is_inflight(fp: str) -> bool:
    try:
        data = json.loads(_inflight_path(fp).read_text(encoding="utf-8"))
        ts = data.get("ts", 0)
    except (OSError, json.JSONDecodeError, ValueError):
        return False
    return (time.time() - ts) < INFLIGHT_MAX_AGE_S


def mark_inflight(fp: str) -> None:
    p = _inflight_path(fp)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"pid": os.getpid(), "ts": time.time()}),
                 encoding="utf-8")


def clear_inflight(fp: str) -> None:
    try:
        _inflight_path(fp).unlink()
    except FileNotFoundError:
        pass
