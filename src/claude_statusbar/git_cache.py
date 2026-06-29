"""Tiny TTL cache for `git status` dirty-state, shared by inline and
daemon. Pure stdlib; no top-level subprocess import."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Optional


TTL_SECONDS = 5
INFLIGHT_MAX_AGE_S = 30


def _cache_root() -> Path:
    return Path(os.path.expanduser("~")) / ".cache" / "claude-statusbar" / "git"


def cache_path_for(toplevel: str) -> Path:
    h = hashlib.sha1(toplevel.encode("utf-8")).hexdigest()
    return _cache_root() / f"{h}.json"


def read_cache(toplevel: str) -> Optional[dict]:
    p = cache_path_for(toplevel)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def is_fresh(entry: Optional[dict], now: Optional[float] = None) -> bool:
    if not entry:
        return False
    ts = entry.get("ts")
    if not isinstance(ts, (int, float)):
        return False
    return (now or time.time()) - ts < TTL_SECONDS


def write_cache_atomic(toplevel: str, entry: dict) -> None:
    p = cache_path_for(toplevel)
    p.parent.mkdir(parents=True, exist_ok=True)
    # Unique temp name (mkstemp) so two concurrent refreshes for the same
    # toplevel never share one `.tmp` and corrupt each other / crash on a
    # half-written file. Atomic replace + unlink-on-error.
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


def _inflight_path(toplevel: str) -> Path:
    return cache_path_for(toplevel).with_suffix(".inflight")


def is_inflight(toplevel: str) -> bool:
    p = _inflight_path(toplevel)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        ts = data.get("ts", 0)
    except (OSError, json.JSONDecodeError, ValueError):
        return False
    return (time.time() - ts) < INFLIGHT_MAX_AGE_S


def mark_inflight(toplevel: str) -> None:
    p = _inflight_path(toplevel)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"pid": os.getpid(), "ts": time.time()}),
                 encoding="utf-8")


def clear_inflight(toplevel: str) -> None:
    try:
        _inflight_path(toplevel).unlink()
    except FileNotFoundError:
        pass
