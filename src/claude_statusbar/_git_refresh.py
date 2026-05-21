"""Detached helper that runs `git status --porcelain=v1` and writes
the dirty cache. Invoked by the inline render path as a background
subprocess; also imported by daemon for in-thread use.

Exits 0 on success, on git-not-found, and on timeout — we never want
to crash the status bar over a failed refresh."""
from __future__ import annotations

import subprocess
import sys
import time

from .git_cache import (
    clear_inflight,
    read_cache,
    write_cache_atomic,
)


def refresh(toplevel: str, timeout_s: float = 2.0) -> None:
    try:
        proc = subprocess.run(
            ["git", "-C", toplevel, "status", "--porcelain=v1"],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        clear_inflight(toplevel)
        return
    if proc.returncode != 0:
        clear_inflight(toplevel)
        return
    dirty = bool(proc.stdout.strip())
    prev = read_cache(toplevel) or {}
    entry = {
        "toplevel": toplevel,
        "branch": prev.get("branch"),
        "dirty": dirty,
        "ts": time.time(),
    }
    write_cache_atomic(toplevel, entry)
    clear_inflight(toplevel)


def main(argv) -> int:
    if len(argv) < 2:
        return 0
    refresh(argv[1])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
