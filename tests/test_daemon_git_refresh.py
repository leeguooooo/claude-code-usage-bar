"""Daemon-side refresh: spawn a tiny git repo, call the refresh hook,
assert the cache file converges."""
import os
import subprocess
import sys

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
