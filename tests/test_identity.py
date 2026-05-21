"""Pure-function tests for identity resolution."""
from pathlib import Path

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
