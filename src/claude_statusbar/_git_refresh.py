"""Detached helper that runs `git status --porcelain=v1` and writes
the dirty cache. Invoked by the inline render path as a background
subprocess; also imported by daemon for in-thread use.

Exits 0 on success, on git-not-found, and on timeout — we never want
to crash the status bar over a failed refresh."""
from __future__ import annotations

import re
import subprocess
import sys
import time
from typing import Optional, Tuple

from .git_cache import (
    clear_inflight,
    read_cache,
    write_cache_atomic,
)

_AHEAD_RE = re.compile(r"ahead (\d+)")
_BEHIND_RE = re.compile(r"behind (\d+)")


def parse_git_status_branch(
    stdout: str,
) -> Tuple[bool, Optional[int], Optional[int]]:
    """Parse `git status --porcelain=v1 --branch` output.

    Returns (dirty, ahead, behind):
      * dirty  — any non-header line means uncommitted changes.
      * ahead/behind — commits relative to the upstream. Both `None` when
        there is no upstream (the `## branch` header has no `...remote`);
        `0` when an upstream exists but that direction is in sync.
    """
    header = ""
    has_changes = False
    for ln in stdout.splitlines():
        if ln.startswith("## "):
            header = ln
        elif ln.strip():
            has_changes = True
    ahead: Optional[int] = None
    behind: Optional[int] = None
    if "..." in header:  # upstream tracking branch present
        ahead, behind = 0, 0
        m = _AHEAD_RE.search(header)
        if m:
            ahead = int(m.group(1))
        m = _BEHIND_RE.search(header)
        if m:
            behind = int(m.group(1))
    return has_changes, ahead, behind


def refresh(toplevel: str, timeout_s: float = 2.0) -> None:
    try:
        proc = subprocess.run(
            ["git", "-C", toplevel, "status", "--porcelain=v1", "--branch"],
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
    dirty, ahead, behind = parse_git_status_branch(proc.stdout)
    prev = read_cache(toplevel) or {}
    entry = {
        "toplevel": toplevel,
        "branch": prev.get("branch"),
        "dirty": dirty,
        "ahead": ahead,
        "behind": behind,
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
