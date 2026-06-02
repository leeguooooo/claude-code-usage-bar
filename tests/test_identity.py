"""Pure-function tests for identity resolution."""
import subprocess
import time
from pathlib import Path
from unittest.mock import patch

from claude_statusbar.identity import (
    IdentityInfo,
    dirty_with_async_refresh,
    read_head,
    resolve_identity,
)


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
    _write(tmp_path / ".git" / "HEAD", "ref: refs/heads/main\n")
    name, detached = read_head(tmp_path)
    assert (name, detached) == ("main", False)


def test_head_branch_with_slash(tmp_path):
    _write(tmp_path / ".git" / "HEAD", "ref: refs/heads/feat/x\n")
    name, detached = read_head(tmp_path)
    assert (name, detached) == ("feat/x", False)


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
    assert info.is_worktree is True  # stdin hint also flips the boolean


def test_detects_worktree_from_local_dotgit_file(tmp_path):
    # Linked worktree: `.git` is a FILE pointing under .../worktrees/<name>.
    main = tmp_path / "main"
    (main / ".git" / "worktrees" / "wt").mkdir(parents=True)
    (main / ".git" / "worktrees" / "wt" / "HEAD").write_text(
        "ref: refs/heads/feat-x\n")
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text(
        f"gitdir: {main / '.git' / 'worktrees' / 'wt'}\n")
    info = resolve_identity({"workspace_current_dir": str(wt)})
    assert info.is_worktree is True
    assert info.branch == "feat-x"


def test_normal_checkout_is_not_a_worktree(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    info = resolve_identity({"workspace_current_dir": str(tmp_path)})
    assert info.is_worktree is False


def test_submodule_is_not_a_worktree(tmp_path):
    # A submodule's `.git` file points under .../modules/<name>, not worktrees.
    sub = tmp_path / "sub"
    sub.mkdir()
    modules = tmp_path / ".git" / "modules" / "sub"
    modules.mkdir(parents=True)
    (modules / "HEAD").write_text("ref: refs/heads/main\n")
    (sub / ".git").write_text(f"gitdir: {modules}\n")
    info = resolve_identity({"workspace_current_dir": str(sub)})
    assert info.is_worktree is False


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


def test_dirty_cache_hit_returns_immediately(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from claude_statusbar.git_cache import write_cache_atomic
    write_cache_atomic("/x", {"toplevel": "/x", "branch": "main",
                              "dirty": True, "ts": time.time()})
    with patch("subprocess.Popen") as popen:
        dirty = dirty_with_async_refresh("/x")
    assert dirty is True
    popen.assert_not_called()


def test_dirty_stale_returns_old_value_and_spawns(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from claude_statusbar.git_cache import write_cache_atomic
    write_cache_atomic("/x", {"toplevel": "/x", "branch": "main",
                              "dirty": True, "ts": time.time() - 999})
    with patch("subprocess.Popen") as popen:
        dirty = dirty_with_async_refresh("/x")
    assert dirty is True
    assert popen.call_count == 1
    _args, kwargs = popen.call_args
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["start_new_session"] is True
    assert kwargs["close_fds"] is True


def test_dirty_missing_returns_none_and_spawns(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    with patch("subprocess.Popen") as popen:
        dirty = dirty_with_async_refresh("/y")
    assert dirty is None
    assert popen.call_count == 1


def test_inflight_prevents_double_spawn(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from claude_statusbar.git_cache import mark_inflight
    mark_inflight("/z")
    with patch("subprocess.Popen") as popen:
        dirty_with_async_refresh("/z")
    popen.assert_not_called()
