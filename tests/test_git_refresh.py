"""End-to-end test: run the refresh helper against a real temporary git
repo and assert the cache file converges."""
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _git(repo, *args):
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={**os.environ,
             "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"},
    )


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q")
    (r / "a").write_text("a")
    _git(r, "add", "a")
    _git(r, "commit", "-m", "init", "-q")
    return r


SRC_DIR = Path(__file__).resolve().parent.parent / "src"


def test_helper_writes_clean_cache(repo, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    out = subprocess.run(
        [sys.executable, "-m", "claude_statusbar._git_refresh", str(repo)],
        env={**os.environ, "PYTHONPATH": str(SRC_DIR), "HOME": str(tmp_path)},
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
    subprocess.run(
        [sys.executable, "-m", "claude_statusbar._git_refresh", str(repo)],
        env={**os.environ, "PYTHONPATH": str(SRC_DIR), "HOME": str(tmp_path)},
        capture_output=True, text=True, timeout=10,
    )
    from claude_statusbar.git_cache import read_cache
    assert read_cache(str(repo))["dirty"] is True


def test_helper_silent_when_git_missing(repo, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    out = subprocess.run(
        [sys.executable, "-m", "claude_statusbar._git_refresh", str(repo)],
        env={"PATH": "", "PYTHONPATH": str(SRC_DIR), "HOME": str(tmp_path)},
        capture_output=True, text=True, timeout=10,
    )
    assert out.returncode == 0
    assert out.stderr == ""
