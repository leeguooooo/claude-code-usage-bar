"""Project + branch identity resolution from Claude Code stdin payload
and the local filesystem. Pure functions; no top-level subprocess."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _resolve_gitdir(start: Path) -> Optional[Path]:
    """Return the directory that actually contains HEAD, or None.

    Handles three cases:
      - `<start>/.git/` is a directory → return that directory
      - `<start>/.git` is a file with `gitdir: <path>` → return resolved path
      - neither → walk upward and retry
    """
    cur = start.resolve() if start.exists() else start
    for candidate in [cur, *cur.parents]:
        dotgit = candidate / ".git"
        if dotgit.is_dir():
            return dotgit
        if dotgit.is_file():
            try:
                text = dotgit.read_text(encoding="utf-8").strip()
            except OSError:
                return None
            if text.startswith("gitdir:"):
                raw = text.split("gitdir:", 1)[1].strip()
                p = Path(raw)
                if not p.is_absolute():
                    p = (candidate / p).resolve()
                return p if p.exists() else None
            return None
    return None


def read_head(start: Path) -> Optional[Tuple[str, bool]]:
    """Return (branch_or_sha7, detached) or None when not in a git repo.

    - `ref: refs/heads/<name>` → (`<name>`, False) even if the ref file
      doesn't exist yet (unborn branch).
    - 40-char hex SHA → (sha[:7], True)
    - anything else → None
    """
    gitdir = _resolve_gitdir(start)
    if gitdir is None:
        return None
    head_file = gitdir / "HEAD"
    try:
        text = head_file.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if text.startswith("ref:"):
        ref = text.split("ref:", 1)[1].strip()
        if ref.startswith("refs/heads/"):
            return ref[len("refs/heads/"):], False
        return ref.split("/")[-1], False
    if _SHA_RE.match(text):
        return text[:7], True
    return None
