"""parse_stdin_data should extract workspace.* fields without breaking
on absence."""
import io
import json
import sys


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
    assert out.get("workspace_repo_name") is None


def test_workspace_present_but_repo_absent():
    out = _run_with_stdin({"workspace": {"current_dir": "/x"}})
    assert out.get("workspace_repo_name") is None
    assert out["workspace_current_dir"] == "/x"
    assert out.get("workspace_git_worktree") is None
