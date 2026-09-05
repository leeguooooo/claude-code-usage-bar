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
import shutil
from functools import lru_cache
from typing import Optional, Tuple

from .git_cache import (
    clear_inflight,
    read_cache,
    write_cache_atomic,
    is_fresh,
    try_claim,
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


@lru_cache(maxsize=1)
def _git_executable():
    return shutil.which('git')


def refresh(toplevel: str, timeout_s: float = 2.0) -> None:
    lock = try_claim(toplevel)
    if lock is None:
        return
    try:
        if not is_fresh(read_cache(toplevel)):
            _refresh_locked(toplevel, timeout_s)
    finally:
        lock.close()
        clear_inflight(toplevel)


def _refresh_locked(toplevel: str, timeout_s: float) -> None:
    def failed():
        entry = read_cache(toplevel) or {'dirty': None}
        entry.update(ts=time.time(), refresh_failed=True)
        write_cache_atomic(toplevel, entry)

    try:
        executable = _git_executable()
        if executable is None:
            failed()
            return
        # --no-optional-locks: never take .git/index.lock for this read. A
        # background `git status` that the status bar polls must not refresh
        # the index lock cache — if our 2s timeout SIGKILLs git mid-write it
        # would strand .git/index.lock and break the user's own next
        # add/commit/rebase. This is why editors poll the same way.
        proc = subprocess.run(
            [executable, "-C", toplevel, "--no-optional-locks",
             "status", "--porcelain=v1", "--branch"],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        failed()
        return
    if proc.returncode != 0:
        failed()
        return
    # Always clear the inflight marker, even if write_cache_atomic raises —
    # otherwise a failed write leaves the marker stranded for INFLIGHT_MAX_AGE_S
    # (30s), freezing dirty-state refreshes for that repo.
    try:
        dirty, ahead, behind = parse_git_status_branch(proc.stdout)
        prev = read_cache(toplevel) or {}
        entry = {
            "toplevel": toplevel,
            "branch": prev.get("branch"),
            "dirty": dirty,
            "ahead": ahead,
            "behind": behind,
            "ts": time.time(),
            "refresh_count": int(prev.get('refresh_count', 0)) + 1,
        }
        write_cache_atomic(toplevel, entry)
    finally:
        clear_inflight(toplevel)


def main(argv) -> int:
    if len(argv) < 2:
        return 0
    refresh(argv[1])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
