# Project + branch identity segment implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in second-line statusbar segment showing
`⤷ <project> ⎇ <branch>●` (dirty marker), reading project name from
Claude Code stdin (`workspace.repo.name`) and branch from `.git/HEAD`
directly, with `git status` deferred to a TTL-cached background refresh.

**Architecture:** Stdin gives us the project name and worktree info for
free. We read `.git/HEAD` synchronously (microseconds) for the branch.
Dirty status is the only slow part — cached at
`~/.cache/claude-statusbar/git/<sha1(toplevel)>.json` with 5 s TTL and
refreshed by a detached `Popen` (inline path) or a daemon-owned
`ThreadPoolExecutor` (daemon path). Render emits a second line joined
by `\n` after the existing first line when `show_project_branch: true`.

**Tech Stack:** Python 3.9+, stdlib only (no new deps). `subprocess`
imported lazily on the refresh branch to preserve `test_import_perf.py`
invariants. ANSI rendered via existing `styles.py`/`themes.py`.

**Spec:** `docs/superpowers/specs/2026-05-21-project-branch-segment-design.md`

---

## File structure

| File | Role |
|---|---|
| `src/claude_statusbar/identity.py` (new) | Pure data resolution: project name, branch, worktree from stdin + filesystem. No subprocess, no I/O writes. |
| `src/claude_statusbar/git_cache.py` (new) | Cache read/write at `~/.cache/claude-statusbar/git/<hash>.json`. Inflight-marker logic. Pure I/O, no git calls. |
| `src/claude_statusbar/_git_refresh.py` (new) | Standalone helper: `python -m claude_statusbar._git_refresh <toplevel> <cache_path>`. Runs `git status --porcelain=v1`, writes cache, cleans inflight. |
| `src/claude_statusbar/core.py` (modify) | `parse_stdin_data()` extracts new `workspace.*` fields. |
| `src/claude_statusbar/config.py` (modify) | Add `show_project_branch: bool = False`. |
| `src/claude_statusbar/styles.py` (modify) | Add `render_identity_line(info, theme)`. |
| `src/claude_statusbar/progress.py` (modify) | `format_status_line` appends identity line when enabled. |
| `src/claude_statusbar/daemon.py` (modify) | Per-repo refresh via `ThreadPoolExecutor`. |
| `src/claude_statusbar/cli.py` (modify) | Surface `cs config show_project_branch on|off`. |
| `tests/test_identity.py` (new) | All TDD assertions described per task. |
| `tests/test_git_cache.py` (new) | Cache hit/miss/corrupt/inflight tests. |
| `tests/test_project_branch_render.py` (new) | End-to-end render assertions for each style. |
| `CHANGELOG.md`, `README.md` (modify) | User-facing announcement. |

---

## Task 1: Extend `parse_stdin_data` to extract workspace fields

**Files:**
- Modify: `src/claude_statusbar/core.py` (function `parse_stdin_data`, around line 445)
- Test: `tests/test_parse_stdin_workspace.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_parse_stdin_workspace.py`:

```python
"""parse_stdin_data should extract workspace.* fields without breaking
on absence."""
import io
import json
import sys

import pytest

from claude_statusbar.core import parse_stdin_data


def _run_with_stdin(payload):
    fake_stdin = io.StringIO(json.dumps(payload))
    fake_stdin.isatty = lambda: False
    real = sys.stdin
    sys.stdin = fake_stdin
    try:
        return parse_stdin_data()
    finally:
        sys.stdin = real


def test_extracts_workspace_repo_name():
    out = _run_with_stdin({
        "workspace": {
            "current_dir": "/repos/proj",
            "project_dir": "/repos/proj",
            "git_worktree": "feature-x",
            "repo": {"host": "github.com", "owner": "me", "name": "proj"},
        },
    })
    assert out["workspace_repo_name"] == "proj"
    assert out["workspace_current_dir"] == "/repos/proj"
    assert out["workspace_project_dir"] == "/repos/proj"
    assert out["workspace_git_worktree"] == "feature-x"


def test_missing_workspace_key_does_not_raise():
    out = _run_with_stdin({"session_id": "abc"})
    assert "workspace_repo_name" not in out or out["workspace_repo_name"] is None


def test_workspace_present_but_repo_absent():
    out = _run_with_stdin({"workspace": {"current_dir": "/x"}})
    assert out.get("workspace_repo_name") is None
    assert out["workspace_current_dir"] == "/x"
    assert out.get("workspace_git_worktree") is None
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/test_parse_stdin_workspace.py -v`
Expected: FAIL — keys not extracted.

- [ ] **Step 3: Implement**

In `src/claude_statusbar/core.py`, inside `parse_stdin_data` after the
`# Version` block (around line 586), add:

```python
        # Workspace identity (used by the optional project/branch segment).
        ws = data.get('workspace') or {}
        if isinstance(ws, dict):
            result['workspace_current_dir'] = ws.get('current_dir') or data.get('cwd')
            result['workspace_project_dir'] = ws.get('project_dir')
            result['workspace_git_worktree'] = ws.get('git_worktree')
            repo = ws.get('repo') or {}
            if isinstance(repo, dict):
                result['workspace_repo_name'] = repo.get('name')
```

- [ ] **Step 4: Run to confirm pass**

Run: `uv run pytest tests/test_parse_stdin_workspace.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_parse_stdin_workspace.py src/claude_statusbar/core.py
git commit -m "feat(core): extract workspace.* fields from Claude Code stdin"
```

---

## Task 2: `identity._read_head` parser

**Files:**
- Create: `src/claude_statusbar/identity.py`
- Test: `tests/test_identity.py` (new)

- [ ] **Step 1: Write failing tests for `.git/HEAD` parsing**

Create `tests/test_identity.py`:

```python
"""Pure-function tests for identity resolution."""
import os
from pathlib import Path

import pytest


from claude_statusbar.identity import read_head


def _write(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_head_branch_ref(tmp_path):
    _write(tmp_path / ".git" / "HEAD", "ref: refs/heads/main\n")
    name, detached = read_head(tmp_path)
    assert (name, detached) == ("main", False)


def test_head_detached_sha(tmp_path):
    sha = "abc1234567890abcdef1234567890abcdef12345"
    _write(tmp_path / ".git" / "HEAD", sha + "\n")
    name, detached = read_head(tmp_path)
    assert detached is True
    assert name == sha[:7]


def test_head_unborn_branch_returns_name(tmp_path):
    # HEAD references a ref that doesn't exist yet (fresh `git init`).
    _write(tmp_path / ".git" / "HEAD", "ref: refs/heads/main\n")
    # refs/heads/main intentionally absent
    name, detached = read_head(tmp_path)
    assert (name, detached) == ("main", False)


def test_dotgit_file_with_absolute_gitdir(tmp_path):
    real = tmp_path / "real-gitdir"
    real.mkdir()
    _write(real / "HEAD", "ref: refs/heads/feat/x\n")
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    _write(worktree / ".git", f"gitdir: {real}\n")
    name, detached = read_head(worktree)
    assert (name, detached) == ("feat/x", False)


def test_dotgit_file_with_relative_gitdir(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    real = tmp_path / "elsewhere"
    real.mkdir()
    _write(real / "HEAD", "ref: refs/heads/main\n")
    _write(sub / ".git", "gitdir: ../elsewhere\n")
    name, detached = read_head(sub)
    assert (name, detached) == ("main", False)


def test_no_git_returns_none(tmp_path):
    assert read_head(tmp_path) is None


def test_malformed_head_returns_none(tmp_path):
    _write(tmp_path / ".git" / "HEAD", "garbage\n")
    assert read_head(tmp_path) is None
```

- [ ] **Step 2: Confirm failures**

Run: `uv run pytest tests/test_identity.py -v`
Expected: ImportError (module doesn't exist yet).

- [ ] **Step 3: Implement `read_head`**

Create `src/claude_statusbar/identity.py`:

```python
"""Project + branch identity resolution from Claude Code stdin payload
and the local filesystem. Pure functions; no subprocess, no network."""
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
        # refs/heads/foo → foo; keep any nested slash (feat/x).
        if ref.startswith("refs/heads/"):
            return ref[len("refs/heads/"):], False
        # Other refs (refs/tags, etc.) — just take last segment.
        return ref.split("/")[-1], False
    if _SHA_RE.match(text):
        return text[:7], True
    return None
```

- [ ] **Step 4: Confirm pass**

Run: `uv run pytest tests/test_identity.py -v`
Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/claude_statusbar/identity.py tests/test_identity.py
git commit -m "feat(identity): parse .git/HEAD with worktree gitdir indirection"
```

---

## Task 3: `identity.resolve_identity` (project name + worktree)

**Files:**
- Modify: `src/claude_statusbar/identity.py`
- Modify: `tests/test_identity.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_identity.py`:

```python
from claude_statusbar.identity import resolve_identity, IdentityInfo


def test_project_name_prefers_repo_name():
    info = resolve_identity({
        "workspace_repo_name": "fancy-repo",
        "workspace_current_dir": "/tmp/elsewhere",
    })
    assert info.project_name == "fancy-repo"


def test_falls_back_to_project_dir_basename():
    info = resolve_identity({
        "workspace_project_dir": "/srv/code/cool-thing",
        "workspace_current_dir": "/srv/code/cool-thing/sub",
    })
    assert info.project_name == "cool-thing"


def test_falls_back_to_current_dir():
    info = resolve_identity({"workspace_current_dir": "/var/www/site"})
    assert info.project_name == "site"


def test_falls_back_to_os_getcwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    info = resolve_identity({})
    assert info.project_name == tmp_path.name


def test_carries_worktree_name():
    info = resolve_identity({
        "workspace_repo_name": "x",
        "workspace_git_worktree": "feat-y",
    })
    assert info.worktree_name == "feat-y"


def test_branch_extracted_from_head(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    info = resolve_identity({"workspace_current_dir": str(tmp_path)})
    assert info.branch == "main"
    assert info.detached is False
    assert info.in_git is True


def test_branch_none_when_no_git(tmp_path):
    info = resolve_identity({"workspace_current_dir": str(tmp_path)})
    assert info.in_git is False
    assert info.branch is None
```

- [ ] **Step 2: Confirm failure**

Run: `uv run pytest tests/test_identity.py -v`
Expected: ImportError on `resolve_identity` / `IdentityInfo`.

- [ ] **Step 3: Implement**

Append to `src/claude_statusbar/identity.py`:

```python
@dataclass
class IdentityInfo:
    project_name: str
    in_git: bool
    branch: Optional[str]
    detached: bool
    worktree_name: Optional[str]
    toplevel: Optional[str]  # absolute path or None when not in git


def _resolve_toplevel(start: Path) -> Optional[Path]:
    gitdir = _resolve_gitdir(start)
    if gitdir is None:
        return None
    # For non-worktree repos: gitdir is `<toplevel>/.git`.
    # For linked worktrees: gitdir is `<repo>/.git/worktrees/<name>`. The
    # checkout dir is what the user cares about; recover it by walking
    # upward from `start` until we find the dir whose `.git` points to
    # `gitdir`. As a fallback, `gitdir.parent` works for the common case.
    if gitdir.name == ".git" and gitdir.parent.is_dir():
        return gitdir.parent
    # Linked worktree: trust `start` (already in the checkout dir).
    cur = start.resolve() if start.exists() else start
    for candidate in [cur, *cur.parents]:
        if (candidate / ".git").exists():
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

    return IdentityInfo(
        project_name=project_name,
        in_git=head is not None,
        branch=head[0] if head else None,
        detached=head[1] if head else False,
        worktree_name=worktree_name,
        toplevel=str(toplevel) if toplevel else None,
    )
```

- [ ] **Step 4: Confirm pass**

Run: `uv run pytest tests/test_identity.py -v`
Expected: 14 PASS (7 head + 7 identity).

- [ ] **Step 5: Commit**

```bash
git add src/claude_statusbar/identity.py tests/test_identity.py
git commit -m "feat(identity): resolve project name + branch + worktree from stdin"
```

---

## Task 4: Git cache read + atomic write

**Files:**
- Create: `src/claude_statusbar/git_cache.py`
- Test: `tests/test_git_cache.py` (new)

- [ ] **Step 1: Write failing tests**

Create `tests/test_git_cache.py`:

```python
"""Git dirty-cache read/write + inflight-marker."""
import json
import time
from pathlib import Path

import pytest

from claude_statusbar.git_cache import (
    cache_path_for,
    read_cache,
    write_cache_atomic,
    is_inflight,
    mark_inflight,
    clear_inflight,
    TTL_SECONDS,
)


def test_cache_path_deterministic(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    a = cache_path_for("/srv/proj")
    b = cache_path_for("/srv/proj")
    assert a == b
    assert a.suffix == ".json"
    assert a.parent.name == "git"


def test_read_returns_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert read_cache("/no/such/repo") is None


def test_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    write_cache_atomic("/srv/proj", {"branch": "main", "dirty": False, "ts": 100.0})
    got = read_cache("/srv/proj")
    assert got["branch"] == "main"
    assert got["dirty"] is False


def test_corrupt_cache_treated_as_miss(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    p = cache_path_for("/srv/proj")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json", encoding="utf-8")
    assert read_cache("/srv/proj") is None


def test_inflight_marker_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert is_inflight("/srv/proj") is False
    mark_inflight("/srv/proj")
    assert is_inflight("/srv/proj") is True
    clear_inflight("/srv/proj")
    assert is_inflight("/srv/proj") is False


def test_stale_inflight_marker_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    mark_inflight("/srv/proj")
    # Backdate marker to >30s ago.
    p = cache_path_for("/srv/proj").with_suffix(".inflight")
    old = time.time() - 60
    p.write_text(json.dumps({"pid": 1, "ts": old}))
    assert is_inflight("/srv/proj") is False


def test_ttl_constant_is_five_seconds():
    assert TTL_SECONDS == 5
```

- [ ] **Step 2: Confirm failure**

Run: `uv run pytest tests/test_git_cache.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

Create `src/claude_statusbar/git_cache.py`:

```python
"""Tiny TTL cache for `git status` dirty-state, shared by inline and
daemon. Pure stdlib; no top-level subprocess import."""
from __future__ import annotations

import hashlib
import json
import os
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
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(entry), encoding="utf-8")
    os.replace(tmp, p)


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
    p.write_text(json.dumps({"pid": os.getpid(), "ts": time.time()}), encoding="utf-8")


def clear_inflight(toplevel: str) -> None:
    try:
        _inflight_path(toplevel).unlink()
    except FileNotFoundError:
        pass
```

- [ ] **Step 4: Confirm pass**

Run: `uv run pytest tests/test_git_cache.py -v`
Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/claude_statusbar/git_cache.py tests/test_git_cache.py
git commit -m "feat(git_cache): TTL-cached dirty state + inflight marker"
```

---

## Task 5: `_git_refresh` helper script

**Files:**
- Create: `src/claude_statusbar/_git_refresh.py`
- Test: `tests/test_git_refresh.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_git_refresh.py`:

```python
"""End-to-end test: run the refresh helper against a real temporary git
repo and assert the cache file converges."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   env={**os.environ,
                        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q")
    (r / "a").write_text("a")
    _git(r, "add", "a")
    _git(r, "commit", "-m", "init", "-q")
    return r


def test_helper_writes_clean_cache(repo, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    src = Path(__file__).resolve().parent.parent / "src"
    out = subprocess.run(
        [sys.executable, "-m", "claude_statusbar._git_refresh", str(repo)],
        env={**os.environ, "PYTHONPATH": str(src), "HOME": str(tmp_path)},
        capture_output=True, text=True, timeout=10,
    )
    assert out.returncode == 0, out.stderr

    from claude_statusbar.git_cache import read_cache
    entry = read_cache(str(repo))
    assert entry is not None
    assert entry["dirty"] is False


def test_helper_detects_dirty(repo, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (repo / "untracked.txt").write_text("hi")
    src = Path(__file__).resolve().parent.parent / "src"
    subprocess.run(
        [sys.executable, "-m", "claude_statusbar._git_refresh", str(repo)],
        env={**os.environ, "PYTHONPATH": str(src), "HOME": str(tmp_path)},
        capture_output=True, text=True, timeout=10,
    )
    from claude_statusbar.git_cache import read_cache
    assert read_cache(str(repo))["dirty"] is True


def test_helper_silent_when_git_missing(repo, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    src = Path(__file__).resolve().parent.parent / "src"
    # Empty PATH so `git` is not found.
    out = subprocess.run(
        [sys.executable, "-m", "claude_statusbar._git_refresh", str(repo)],
        env={"PATH": "", "PYTHONPATH": str(src), "HOME": str(tmp_path)},
        capture_output=True, text=True, timeout=10,
    )
    assert out.returncode == 0
    assert out.stderr == ""
```

- [ ] **Step 2: Confirm failure**

Run: `uv run pytest tests/test_git_refresh.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement helper**

Create `src/claude_statusbar/_git_refresh.py`:

```python
"""Detached helper that runs `git status --porcelain=v1` and writes
the dirty cache. Invoked by inline render path as a background
subprocess; also imported by daemon for in-thread use.

Exits 0 on success, on git-not-found, and on timeout (we never want
to crash the status bar over a failed refresh)."""
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
        "branch": prev.get("branch"),  # branch comes from HEAD on render side
        "dirty": dirty,
        "ts": time.time(),
    }
    write_cache_atomic(toplevel, entry)
    clear_inflight(toplevel)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        return 0
    refresh(argv[1])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

- [ ] **Step 4: Confirm pass**

Run: `uv run pytest tests/test_git_refresh.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/claude_statusbar/_git_refresh.py tests/test_git_refresh.py
git commit -m "feat(git_refresh): detached helper for background dirty refresh"
```

---

## Task 6: Inline spawn wrapper + import-perf invariant test

**Files:**
- Modify: `src/claude_statusbar/identity.py` (add `dirty_with_async_refresh`)
- Modify: `tests/test_identity.py`
- Modify: `tests/test_import_perf.py` (add assertion that `identity` is safe to import)

- [ ] **Step 1: Write test for spawn behavior**

Append to `tests/test_identity.py`:

```python
import time
from unittest.mock import patch


def test_dirty_cache_hit_returns_immediately(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from claude_statusbar.git_cache import write_cache_atomic
    write_cache_atomic("/x", {"toplevel": "/x", "branch": "main",
                              "dirty": True, "ts": time.time()})
    from claude_statusbar.identity import dirty_with_async_refresh
    with patch("subprocess.Popen") as popen:
        dirty = dirty_with_async_refresh("/x")
    assert dirty is True
    popen.assert_not_called()


def test_dirty_stale_returns_old_value_and_spawns(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from claude_statusbar.git_cache import write_cache_atomic
    write_cache_atomic("/x", {"toplevel": "/x", "branch": "main",
                              "dirty": True, "ts": time.time() - 999})
    from claude_statusbar.identity import dirty_with_async_refresh
    with patch("subprocess.Popen") as popen:
        dirty = dirty_with_async_refresh("/x")
    assert dirty is True  # stale value still returned
    assert popen.call_count == 1
    args, kwargs = popen.call_args
    assert kwargs["stdin"] is subprocess_devnull()
    assert kwargs["start_new_session"] is True
    assert kwargs["close_fds"] is True


def test_dirty_missing_returns_none_and_spawns(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from claude_statusbar.identity import dirty_with_async_refresh
    with patch("subprocess.Popen") as popen:
        dirty = dirty_with_async_refresh("/y")
    assert dirty is None
    assert popen.call_count == 1


def test_inflight_prevents_double_spawn(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from claude_statusbar.git_cache import mark_inflight
    mark_inflight("/z")
    from claude_statusbar.identity import dirty_with_async_refresh
    with patch("subprocess.Popen") as popen:
        dirty_with_async_refresh("/z")
    popen.assert_not_called()


def subprocess_devnull():
    import subprocess
    return subprocess.DEVNULL
```

- [ ] **Step 2: Confirm failure**

Run: `uv run pytest tests/test_identity.py -v -k dirty_`
Expected: ImportError on `dirty_with_async_refresh`.

- [ ] **Step 3: Implement**

Append to `src/claude_statusbar/identity.py`:

```python
def dirty_with_async_refresh(toplevel: str) -> Optional[bool]:
    """Return the cached dirty state, kicking off a background refresh
    if the cache is stale or missing. Never blocks on git.

    Lazy-imports `subprocess` so `test_import_perf.py` invariants hold
    on the render hot path when the cache is fresh.
    """
    from . import git_cache  # local import keeps top-level imports clean

    entry = git_cache.read_cache(toplevel)
    fresh = git_cache.is_fresh(entry)
    if fresh:
        return bool(entry.get("dirty"))

    # Stale or missing — try to spawn a refresh, but don't spawn twice.
    if not git_cache.is_inflight(toplevel):
        git_cache.mark_inflight(toplevel)
        try:
            import subprocess  # lazy
            import sys
            subprocess.Popen(
                [sys.executable, "-m", "claude_statusbar._git_refresh", toplevel],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                start_new_session=True,
            )
        except (OSError, ValueError):
            git_cache.clear_inflight(toplevel)

    # Return whatever we had (may be None if cache never existed).
    return None if entry is None else bool(entry.get("dirty"))
```

- [ ] **Step 4: Add import-perf invariant**

In `tests/test_import_perf.py`, append:

```python
def test_identity_module_safe_to_import():
    """Importing claude_statusbar.identity must not pull in subprocess."""
    imports = _list_imports_for("claude_statusbar.identity")
    assert "subprocess" not in imports, (
        "identity.py must lazy-import subprocess inside the stale branch only"
    )
```

- [ ] **Step 5: Confirm all pass**

Run: `uv run pytest tests/test_identity.py tests/test_import_perf.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/claude_statusbar/identity.py tests/test_identity.py tests/test_import_perf.py
git commit -m "feat(identity): non-blocking dirty-with-async-refresh wrapper"
```

---

## Task 7: Config flag `show_project_branch`

**Files:**
- Modify: `src/claude_statusbar/config.py`
- Test: `tests/test_config_project_branch.py` (new)

- [ ] **Step 1: Failing test**

Create `tests/test_config_project_branch.py`:

```python
from claude_statusbar.config import StatusbarConfig, load_config, set_value


def test_default_off():
    assert StatusbarConfig().show_project_branch is False


def test_set_via_set_value(tmp_path):
    p = tmp_path / "c.json"
    cfg = set_value("show_project_branch", "true", path=p)
    assert cfg.show_project_branch is True
    assert load_config(p).show_project_branch is True


def test_set_off(tmp_path):
    p = tmp_path / "c.json"
    set_value("show_project_branch", "true", path=p)
    cfg = set_value("show_project_branch", "off", path=p)
    assert cfg.show_project_branch is False
```

- [ ] **Step 2: Confirm failure**

Run: `uv run pytest tests/test_config_project_branch.py -v`
Expected: AttributeError / KeyError.

- [ ] **Step 3: Implement**

In `src/claude_statusbar/config.py`:

- Add `show_project_branch: bool = False` to `StatusbarConfig` after `show_cache_age`.
- In `load_config`, add `show_project_branch=_to_bool(raw.get("show_project_branch", False))`.
- Add `"show_project_branch"` to `VALID_KEYS` and `_BOOL_KEYS`.

- [ ] **Step 4: Confirm pass**

Run: `uv run pytest tests/test_config_project_branch.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/claude_statusbar/config.py tests/test_config_project_branch.py
git commit -m "feat(config): add show_project_branch (default off)"
```

---

## Task 8: `render_identity_line` in `styles.py`

**Files:**
- Modify: `src/claude_statusbar/styles.py`
- Test: `tests/test_project_branch_render.py` (new)

- [ ] **Step 1: Failing test**

Create `tests/test_project_branch_render.py`:

```python
from claude_statusbar.identity import IdentityInfo
from claude_statusbar.styles import render_identity_line
from claude_statusbar.themes import get_theme


THEME = get_theme("graphite")


def test_with_branch_and_clean():
    s = render_identity_line(IdentityInfo(
        project_name="proj", in_git=True, branch="main", detached=False,
        worktree_name=None, toplevel="/x"), theme=THEME, dirty=False, use_color=False)
    assert "proj" in s
    assert "main" in s
    assert "●" not in s
    assert "⤷" in s
    assert "⎇" in s


def test_with_branch_and_dirty():
    s = render_identity_line(IdentityInfo(
        project_name="proj", in_git=True, branch="main", detached=False,
        worktree_name=None, toplevel="/x"), theme=THEME, dirty=True, use_color=False)
    assert "●" in s


def test_no_git_shows_no_git_tag():
    s = render_identity_line(IdentityInfo(
        project_name="proj", in_git=False, branch=None, detached=False,
        worktree_name=None, toplevel=None), theme=THEME, dirty=None, use_color=False)
    assert "(no git)" in s
    assert "⎇" not in s


def test_detached_head_uses_short_sha():
    s = render_identity_line(IdentityInfo(
        project_name="proj", in_git=True, branch="abc1234", detached=True,
        worktree_name=None, toplevel="/x"), theme=THEME, dirty=False, use_color=False)
    assert "abc1234" in s


def test_worktree_suffix():
    s = render_identity_line(IdentityInfo(
        project_name="proj", in_git=True, branch="feat-x", detached=False,
        worktree_name="feat-x", toplevel="/x"), theme=THEME, dirty=False, use_color=False)
    assert "feat-x" in s
    assert "worktree" in s.lower()
```

- [ ] **Step 2: Confirm failure**

Run: `uv run pytest tests/test_project_branch_render.py -v`
Expected: ImportError on `render_identity_line`.

- [ ] **Step 3: Implement**

Add to `src/claude_statusbar/styles.py` (after the existing renderers):

```python
def render_identity_line(info, *, theme: Theme, dirty,
                          use_color: bool = True) -> str:
    """Render the optional 2nd-line `⤷ <project> ⎇ <branch>●` segment.

    `dirty` is True / False / None — None means "unknown" (cache miss);
    in that case we omit the dot rather than asserting clean.
    """
    MUTE = _fg(theme.mute)
    EDGE = _fg(theme.edge)
    INK  = _fg(theme.pill_ink)
    HOT  = _fg(theme.s_warn)

    if not use_color:
        # Plain-text mode used by tests / no-color terminals.
        head = f"⤷ {info.project_name}"
        if not info.in_git:
            tail = " (no git)"
        else:
            branch = info.branch or "?"
            dot = "●" if dirty else ""
            tail = f" ⎇ {branch}{dot}"
        if info.worktree_name:
            tail += f" [worktree: {info.worktree_name}]"
        return head + tail

    head = f"{MUTE}⤷ {info.project_name}{RESET}"
    if not info.in_git:
        body = f" {MUTE}{ITAL}(no git){RESET}"
    else:
        branch = info.branch or "?"
        branch_styled = (f"{MUTE}{ITAL}{branch}{RESET}"
                         if info.detached else f"{INK}{branch}{RESET}")
        dot = f"{HOT}●{RESET}" if dirty else ""
        body = f" {EDGE}⎇{RESET} {branch_styled}{dot}"
    if info.worktree_name:
        body += f" {MUTE}[worktree: {info.worktree_name}]{RESET}"
    return head + body
```

- [ ] **Step 4: Confirm pass**

Run: `uv run pytest tests/test_project_branch_render.py -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/claude_statusbar/styles.py tests/test_project_branch_render.py
git commit -m "feat(styles): render_identity_line for project + branch 2nd line"
```

---

## Task 9: Wire identity line into the style dispatcher

`format_status_line` is only consumed by `render_classic`. The other
two styles (capsule, hairline) have their own renderers. To make the
identity line work across all three styles without duplicating the
glue, we append it inside `styles.render()` (the public dispatcher at
`styles.py:260-268`), and pass the identity info / dirty flag through
its `**kwargs`. The call to `styles.render(...)` happens inside `core.main()`
(grep `grep -n "styles.render\|render(style" src/claude_statusbar/core.py` to confirm — likely a single call site).

**Files:**
- Modify: `src/claude_statusbar/styles.py` (`render()` dispatcher, lines ~260-268)
- Modify: `src/claude_statusbar/core.py` (pass `show_project_branch` + identity through to `styles.render`)
- Test: `tests/test_project_branch_render.py` (extend)

- [ ] **Step 1: Read current signature**

Look at `src/claude_statusbar/progress.py:220` — the `format_status_line` signature. Note the existing kwargs.

- [ ] **Step 2: Write integration test**

Append to `tests/test_project_branch_render.py`:

```python
def test_dispatcher_appends_identity_when_enabled():
    from claude_statusbar import styles
    out = styles.render(
        "classic",
        msgs_pct=10, weekly_pct=20, model="Opus 4.7",
        reset_5h="4h", reset_7d="6d",
        use_color=False, theme=THEME,
        show_project_branch=True,
        identity=IdentityInfo(project_name="demo", in_git=True,
                              branch="main", detached=False,
                              worktree_name=None, toplevel="/x"),
        identity_dirty=False,
    )
    assert "\n" in out
    second = out.split("\n", 1)[1]
    assert "demo" in second and "main" in second


def test_dispatcher_omits_identity_when_disabled():
    from claude_statusbar import styles
    out = styles.render(
        "classic",
        msgs_pct=10, weekly_pct=20, model="Opus 4.7",
        reset_5h="4h", reset_7d="6d",
        use_color=False, theme=THEME,
        show_project_branch=False,
    )
    assert "\n" not in out


def test_dispatcher_applies_to_capsule_too():
    from claude_statusbar import styles
    out = styles.render(
        "capsule",
        msgs_pct=10, weekly_pct=20, model="Opus 4.7",
        reset_5h="4h", reset_7d="6d",
        use_color=False, theme=THEME,
        show_project_branch=True,
        identity=IdentityInfo(project_name="demo", in_git=True,
                              branch="main", detached=False,
                              worktree_name=None, toplevel="/x"),
        identity_dirty=False,
    )
    assert "demo" in out and "main" in out
```

- [ ] **Step 3: Confirm failure**

Run: `uv run pytest tests/test_project_branch_render.py -v`
Expected: 2 new FAIL.

- [ ] **Step 4: Implement in the dispatcher**

In `src/claude_statusbar/styles.py`, change `render()` to extract the
identity-related kwargs, call the underlying style renderer normally,
then post-process:

```python
def render(style: str, **kwargs) -> str:
    show_pb = kwargs.pop("show_project_branch", False)
    info    = kwargs.pop("identity", None)
    dirty   = kwargs.pop("identity_dirty", None)
    theme   = kwargs.get("theme") or get_theme("graphite")
    use_color = kwargs.get("use_color", True)

    fn = RENDERERS.get(style, render_classic)
    out = fn(**kwargs)

    if show_pb and info is not None:
        out = out + "\n" + render_identity_line(
            info, theme=theme, dirty=dirty, use_color=use_color,
        )
    return out
```

(The individual renderers already absorb unknown kwargs via `**_ignored`, so popping them here is safe even if a caller passes them along.)

- [ ] **Step 5: Wire from `core.main`**

Find the call site with:

```bash
grep -n "styles.render\|RENDERERS\[" src/claude_statusbar/core.py
```

At that call site:

- The resolved `StatusbarConfig` is already loaded (look for `load_config` higher in the same function).
- If `cfg.show_project_branch`:
  - `from .identity import resolve_identity, dirty_with_async_refresh`
  - `info = resolve_identity(stdin_data)`
  - `dirty = dirty_with_async_refresh(info.toplevel) if info.toplevel else None`
  - Add to the kwargs being passed to `styles.render(...)`: `show_project_branch=True, identity=info, identity_dirty=dirty`.
- If `cfg.show_project_branch` is False: change nothing — `render()` defaults to no identity line.

- [ ] **Step 6: Confirm pass**

Run: `uv run pytest -v`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add src/claude_statusbar/styles.py src/claude_statusbar/core.py tests/test_project_branch_render.py
git commit -m "feat(styles): dispatcher appends identity line across all styles"
```

---

## Task 10: Daemon refresh worker

**Files:**
- Modify: `src/claude_statusbar/daemon.py`
- Test: `tests/test_daemon_git_refresh.py` (new, integration-style)

- [ ] **Step 1: Write integration test**

Create `tests/test_daemon_git_refresh.py`:

```python
"""Daemon-side refresh: spawn a tiny git repo, call the daemon's tick
hook, assert the cache file converges."""
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   env={**os.environ,
                        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "r"
    r.mkdir()
    _git(r, "init", "-q")
    (r / "a").write_text("a")
    _git(r, "add", "a")
    _git(r, "commit", "-m", "x", "-q")
    return r


def test_daemon_refresh_writes_cache(repo, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from claude_statusbar.daemon import _refresh_repo_sync
    _refresh_repo_sync(str(repo))
    from claude_statusbar.git_cache import read_cache
    entry = read_cache(str(repo))
    assert entry is not None
    assert entry["dirty"] is False
```

- [ ] **Step 2: Confirm failure**

Run: `uv run pytest tests/test_daemon_git_refresh.py -v`
Expected: ImportError on `_refresh_repo_sync`.

- [ ] **Step 3: Implement**

In `src/claude_statusbar/daemon.py`, add at module top (alongside existing imports):

```python
from concurrent.futures import ThreadPoolExecutor
import threading
from . import git_cache
from ._git_refresh import refresh as _refresh_repo_sync
```

Add a module-level lazily-created executor:

```python
_REFRESH_EXECUTOR = None
_REFRESH_LOCKS: dict = {}
_REFRESH_LOCKS_LOCK = threading.Lock()


def _get_executor():
    global _REFRESH_EXECUTOR
    if _REFRESH_EXECUTOR is None:
        _REFRESH_EXECUTOR = ThreadPoolExecutor(max_workers=4,
                                               thread_name_prefix="cs-git")
    return _REFRESH_EXECUTOR


def _maybe_refresh_repo(toplevel: str) -> None:
    """Submit a refresh job if the cache is stale and no refresh is
    already running for this repo."""
    entry = git_cache.read_cache(toplevel)
    if git_cache.is_fresh(entry):
        return
    if git_cache.is_inflight(toplevel):
        return
    with _REFRESH_LOCKS_LOCK:
        lock = _REFRESH_LOCKS.setdefault(toplevel, threading.Lock())
    if not lock.acquire(blocking=False):
        return
    git_cache.mark_inflight(toplevel)

    def _job():
        try:
            _refresh_repo_sync(toplevel)
        finally:
            lock.release()
    _get_executor().submit(_job)
```

Inside the daemon's per-tick rendering of each session, after parsing
the session's stdin, if `cfg.show_project_branch`:

```python
        from .identity import resolve_identity
        info = resolve_identity(session_stdin)
        if info.toplevel:
            _maybe_refresh_repo(info.toplevel)
```

The actual render call also passes the identity info just like the
inline path.

- [ ] **Step 4: Confirm pass**

Run: `uv run pytest tests/test_daemon_git_refresh.py -v`
Expected: 1 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/claude_statusbar/daemon.py tests/test_daemon_git_refresh.py
git commit -m "feat(daemon): per-repo dirty refresh via ThreadPoolExecutor"
```

---

## Task 11: CLI `cs config show_project_branch on|off`

**Files:**
- Modify: `src/claude_statusbar/cli.py` (config subcommand handler)
- Test: covered transitively by Task 7's `set_value` tests + a smoke test

- [ ] **Step 1: Smoke test**

Append to `tests/test_config_project_branch.py`:

```python
import subprocess
import sys


def test_cli_set_show_project_branch(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    src = (tmp_path.parent / "src").resolve()
    # Prefer running through the installed entry point if available.
    out = subprocess.run(
        [sys.executable, "-m", "claude_statusbar.cli", "config",
         "set", "show_project_branch", "true"],
        capture_output=True, text=True,
    )
    assert out.returncode == 0, out.stderr
```

(Skip with `pytest.mark.skipif` if `cs config set` already routes via
`set_value`; this test only verifies no traceback. If `cli.py` already
supports arbitrary `VALID_KEYS`, no code change is needed — adding
`show_project_branch` to `VALID_KEYS` in Task 7 is enough.)

- [ ] **Step 2: If failing, expose in cli.py**

Run: `uv run pytest tests/test_config_project_branch.py::test_cli_set_show_project_branch -v`

If FAIL: locate the `config` subcommand handler in `src/claude_statusbar/cli.py` (`grep -n "def cmd_config\|'config'" src/claude_statusbar/cli.py`) and confirm it dispatches via `config.set_value(key, value)`. Adding the key to `VALID_KEYS` (Task 7) is normally sufficient.

- [ ] **Step 3: Confirm pass + commit**

```bash
git add tests/test_config_project_branch.py
git commit -m "test(cli): smoke test cs config set show_project_branch"
```

---

## Task 12: README + CHANGELOG

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: CHANGELOG entry**

Add a new top section to `CHANGELOG.md`:

```markdown
## [Unreleased]

### Added
- Opt-in project + branch identity segment on a 2nd line. Enable with
  `cs config set show_project_branch true`. Shows the current project
  (from Claude Code's `workspace.repo.name` stdin field, falling back
  to cwd basename), the git branch (read from `.git/HEAD` directly),
  and a `●` dirty marker when the working tree has uncommitted changes.
  Outside a git repo: `⤷ <project> (no git)`.
- Daemon owns dirty refresh for all open sessions; inline path uses a
  detached `python -m claude_statusbar._git_refresh` background worker
  so the per-second render stays well under its 30 ms budget.
```

- [ ] **Step 2: README section**

In `README.md`, in the "Configuration" or equivalent section, add:

```markdown
### Project + branch (opt-in)

Turn on a second status-bar line that shows the project and git branch:

    cs config set show_project_branch true

Disable with `cs config set show_project_branch false`. The branch is
read from `.git/HEAD` directly (microseconds, no `git` fork). Dirty
state is refreshed in the background and cached for 5 seconds, so the
status bar stays fast even on big monorepos.
```

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md README.md
git commit -m "docs: announce project+branch segment (opt-in)"
```

---

## Task 13: Full regression sweep + `cs preview`

- [ ] **Step 1: Run full suite**

Run: `uv run pytest -v`
Expected: all green (existing + 11 new test files).

- [ ] **Step 2: Visual sanity check**

Run:

```bash
cs config set show_project_branch true
cs preview
```

Expected: every style × theme combination renders a second line. Verify
visually that:
- `⤷` glyph renders
- branch name shown
- `●` appears when current repo is dirty
- no garbled escape sequences

- [ ] **Step 3: Inline timing check**

Run (inside the repo, with feature on):

```bash
time echo '{"workspace":{"current_dir":"'"$PWD"'","repo":{"name":"claude-statusbar-monitor"}},"session_id":"x"}' | cs
```

Expected: total wall time < 100 ms on second invocation (first invocation may include cache miss + Popen).

- [ ] **Step 4: If all good, no commit needed (no changes).** If any fix needed, commit it with a `fix(...)` prefix.

---

## Done criteria

- All new tests pass.
- `test_import_perf.py` still passes (subprocess banned at top of render path, lazy import inside stale branch).
- `cs config set show_project_branch true` produces a working second line.
- Default off — existing users see no change on upgrade.
- README + CHANGELOG updated.
- `cs preview` renders cleanly across all styles and themes.
