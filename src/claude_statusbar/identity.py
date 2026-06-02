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


@dataclass
class IdentityInfo:
    project_name: str
    in_git: bool
    branch: Optional[str]
    detached: bool
    worktree_name: Optional[str]
    toplevel: Optional[str]
    is_worktree: bool = False


def _detect_worktree(start: Path) -> bool:
    """True when `start` sits inside a *linked* git worktree.

    A linked worktree's `.git` is a FILE whose `gitdir:` points under the
    main repo's `.git/worktrees/<name>/`. A submodule's `.git` file points
    under `.git/modules/<name>/` instead — so the `worktrees` segment is
    what distinguishes a worktree from both a normal checkout (`.git` is a
    directory) and a submodule. Local + reliable; no dependency on Claude
    Code passing `workspace_git_worktree`.
    """
    cur = start.resolve() if start.exists() else start
    for candidate in [cur, *cur.parents]:
        dotgit = candidate / ".git"
        if dotgit.is_dir():
            return False
        if dotgit.is_file():
            try:
                text = dotgit.read_text(encoding="utf-8").strip()
            except OSError:
                return False
            return "worktrees/" in text or "worktrees\\" in text
    return False


def _resolve_toplevel(start: Path) -> Optional[Path]:
    """Best-effort working-tree root for a path inside a git checkout.

    For a normal `.git/` directory layout, returns the directory that
    contains `.git/`. For a linked worktree (`.git` is a file pointing
    elsewhere), returns the directory containing that `.git` file
    (the checkout dir), not the linked gitdir.
    """
    cur = start.resolve() if start.exists() else start
    for candidate in [cur, *cur.parents]:
        dotgit = candidate / ".git"
        if dotgit.exists():
            return candidate
    return None


def resolve_identity(stdin: dict) -> IdentityInfo:
    repo_name = stdin.get("workspace_repo_name")
    project_dir = stdin.get("workspace_project_dir")
    current_dir = stdin.get("workspace_current_dir")
    worktree_name = stdin.get("workspace_git_worktree")

    if repo_name:
        project_name = repo_name
    elif project_dir:
        project_name = os.path.basename(project_dir.rstrip("/")) or project_dir
    elif current_dir:
        project_name = os.path.basename(current_dir.rstrip("/")) or current_dir
    else:
        project_name = os.path.basename(os.getcwd()) or "?"

    start = Path(current_dir or project_dir or os.getcwd())
    head = read_head(start)
    toplevel = _resolve_toplevel(start) if head else None
    # Trust the local filesystem first (works even when CC omits the field),
    # fall back to the stdin hint for the rare case the cwd isn't on disk.
    is_worktree = (_detect_worktree(start) if head else False) or bool(worktree_name)

    return IdentityInfo(
        project_name=project_name,
        in_git=head is not None,
        branch=head[0] if head else None,
        detached=head[1] if head else False,
        worktree_name=worktree_name,
        toplevel=str(toplevel) if toplevel else None,
        is_worktree=is_worktree,
    )


def dirty_with_async_refresh(toplevel: str) -> Optional[bool]:
    """Return the cached dirty state, kicking off a background refresh
    if the cache is stale or missing. Never blocks on git.

    Lazy-imports `subprocess` so `test_import_perf.py` invariants hold
    on the render hot path when the cache is fresh.
    """
    from . import git_cache  # local import keeps top-level imports clean

    entry = git_cache.read_cache(toplevel)
    if git_cache.is_fresh(entry):
        return bool(entry.get("dirty"))

    if not git_cache.is_inflight(toplevel):
        git_cache.mark_inflight(toplevel)
        try:
            import subprocess  # lazy
            import sys
            subprocess.Popen(
                [sys.executable, "-m", "claude_statusbar._git_refresh",
                 toplevel],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                start_new_session=True,
            )
        except (OSError, ValueError):
            git_cache.clear_inflight(toplevel)

    return None if entry is None else bool(entry.get("dirty"))


def read_ahead_behind(toplevel: str) -> Tuple[Optional[int], Optional[int]]:
    """Return (ahead, behind) from the git cache without triggering a refresh.

    The refresh is already kicked off by ``dirty_with_async_refresh`` (both
    values come from the same ``git status --branch`` call), so this is a
    cheap cache read. (None, None) when unknown / no upstream / cache miss.
    """
    from . import git_cache

    entry = git_cache.read_cache(toplevel)
    if entry is None:
        return None, None
    return entry.get("ahead"), entry.get("behind")
