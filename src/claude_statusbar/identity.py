"""Project + branch identity resolution from Claude Code stdin payload
and the local filesystem. Pure functions; no top-level subprocess."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple, Optional, Tuple

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
# ".../<repo>/.git/worktrees/<name>" — the gitdir a linked worktree points at.
_WT_GITDIR_RE = re.compile(r"^(?P<root>.+)/\.git/worktrees/(?P<name>[^/]+)$")


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
    # How many linked worktrees this repo has in total (this one included).
    # 0 when unknown / not in a worktree.
    worktree_count: int = 0


class _Worktree(NamedTuple):
    name: str          # this worktree's registered name
    repo_name: str     # the main repo's directory name
    registry: Path     # the main repo's `.git/worktrees/` dir


def _parse_worktree(start: Path) -> Optional[_Worktree]:
    """A `_Worktree` when `start` sits inside a *linked* git worktree, else
    None.

    A linked worktree's `.git` is a FILE whose `gitdir:` points under the
    main repo's `.git/worktrees/<name>/`. A submodule's `.git` file points
    under `.git/modules/<name>/` instead — so the `worktrees` segment is
    what distinguishes a worktree from both a normal checkout (`.git` is a
    directory) and a submodule. Local + reliable; no dependency on Claude
    Code passing `workspace_git_worktree` (it omits the field for worktrees
    it didn't create itself).

    The main repo's directory name comes back too so the identity line can
    show the *repo* as the anchor even when stdin carries no repo name —
    otherwise a worktree checkout would masquerade as its own project. So
    does the `.git/worktrees/` registry dir, which is the whole sibling list.
    """
    cur = start.resolve() if start.exists() else start
    for candidate in [cur, *cur.parents]:
        dotgit = candidate / ".git"
        if dotgit.is_dir():
            return None
        if dotgit.is_file():
            try:
                text = dotgit.read_text(encoding="utf-8").strip()
            except OSError:
                return None
            if not text.startswith("gitdir:"):
                return None
            raw = text.split("gitdir:", 1)[1].strip()
            m = _WT_GITDIR_RE.match(raw.replace("\\", "/").rstrip("/"))
            if m is None:
                return None  # submodule (.git/modules/...) or something else
            repo_root = m.group("root").rstrip("/")
            repo_name = os.path.basename(repo_root) or repo_root
            return _Worktree(m.group("name"), repo_name,
                             Path(raw).parent)
    return None


_WORKTREE_COUNTS = {}


def count_live_worktrees(registry: Path) -> int:
    if not _BACKGROUND_COLLECTORS:
        return _count_live_worktrees(registry)
    import time
    now = time.monotonic()
    try:
        st = registry.stat()
        sig = (st.st_ino, st.st_mtime_ns)
    except OSError:
        return 0
    old = _WORKTREE_COUNTS.get(str(registry))
    if old and old[0] == sig and now - old[1] < 30:
        return old[2]
    count = _count_live_worktrees(registry)
    if len(_WORKTREE_COUNTS) >= 128:
        _WORKTREE_COUNTS.clear()
    _WORKTREE_COUNTS[str(registry)] = (sig, now, count)
    return count


def _count_live_worktrees(registry: Path) -> int:
    """How many linked worktrees the repo owning `registry` still has.

    `registry` is the main repo's `.git/worktrees/` dir — one entry per
    linked worktree. Entries outlive their checkout: `rm -rf`-ing a worktree
    dir leaves the entry behind until someone runs `git worktree prune`, so a
    bare `len(listdir)` overcounts. Each entry's `gitdir` file points at the
    checkout's `.git` file; if that path is gone, the entry is a prunable
    ghost and must not be counted — a number you can't trust is worse on a
    status line than no number at all.

    Pure filesystem: one dir scan plus one small read per entry, no
    subprocess. Returns 0 when the registry can't be read.
    """
    try:
        entries = sorted(registry.iterdir())
    except OSError:
        return 0
    live = 0
    for entry in entries:
        try:
            gitdir = (entry / "gitdir").read_text(encoding="utf-8").strip()
        except OSError:
            continue  # no gitdir file → not a usable worktree entry
        if gitdir and Path(gitdir).exists():
            live += 1
    return live


def _detect_worktree(start: Path) -> bool:
    """True when `start` sits inside a linked git worktree."""
    return _parse_worktree(start) is not None


def strip_repo_prefix(name: str, anchor: str) -> str:
    """``("repo-wt-x", "repo") -> "wt-x"``.

    Worktree dirs are conventionally named after the repo they belong to.
    The repo already anchors the identity line, so repeating it there costs
    width and says nothing — drop it, but never reduce the name to nothing.
    """
    if not name or not anchor or name == anchor:
        return name
    for sep in ("-", "_", "."):
        prefix = anchor + sep
        if name.startswith(prefix) and len(name) > len(prefix):
            return name[len(prefix):]
    return name


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

    start = Path(current_dir or project_dir or os.getcwd())
    head = read_head(start)
    toplevel = _resolve_toplevel(start) if head else None
    # Trust the local filesystem first (works even when CC omits the field),
    # fall back to the stdin hint for the rare case the cwd isn't on disk.
    wt = _parse_worktree(start) if head else None
    is_worktree = wt is not None or bool(worktree_name)
    if wt is not None and not worktree_name:
        worktree_name = strip_repo_prefix(wt.name, wt.repo_name)
    if wt is not None:
        worktree_count = count_live_worktrees(wt.registry)
    elif toplevel is not None:
        # Main checkout: count the linked worktrees hanging off *this* repo.
        # "I'm in the main tree and three parallel ones exist" is the other
        # half of the same fact — and the half you're in when you edit the
        # wrong tree by accident.
        worktree_count = count_live_worktrees(toplevel / ".git" / "worktrees")
    else:
        worktree_count = 0

    if repo_name:
        project_name = repo_name
    elif wt is not None:
        # In a worktree the checkout dir names the *worktree*, not the repo —
        # so the main repo's dir name is the honest anchor here.
        project_name = wt.repo_name
    elif project_dir:
        project_name = os.path.basename(project_dir.rstrip("/")) or project_dir
    elif current_dir:
        project_name = os.path.basename(current_dir.rstrip("/")) or current_dir
    else:
        project_name = os.path.basename(os.getcwd()) or "?"

    return IdentityInfo(
        project_name=project_name,
        in_git=head is not None,
        branch=head[0] if head else None,
        detached=head[1] if head else False,
        worktree_name=worktree_name,
        toplevel=str(toplevel) if toplevel else None,
        is_worktree=is_worktree,
        worktree_count=worktree_count,
    )


_BACKGROUND_COLLECTORS = False


def dirty_with_async_refresh(toplevel: str) -> Optional[bool]:
    """Return the cached dirty state, kicking off a background refresh
    if the cache is stale or missing. Never blocks on git.

    Lazy-imports `subprocess` so `test_import_perf.py` invariants hold
    on the render hot path when the cache is fresh.
    """
    from . import git_cache  # local import keeps top-level imports clean

    entry = git_cache.read_cache(toplevel)
    if git_cache.is_fresh(entry):
        return entry.get("dirty")

    if _BACKGROUND_COLLECTORS:
        from .refresh_pool import submit
        from ._git_refresh import refresh
        submit(('git', toplevel), refresh, toplevel)
        return None if entry is None else entry.get('dirty')

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

    return None if entry is None else entry.get("dirty")


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
