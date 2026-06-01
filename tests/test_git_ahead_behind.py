"""git ahead/behind: porcelain --branch parsing + identity-line rendering."""

from claude_statusbar._git_refresh import parse_git_status_branch
from claude_statusbar.identity import IdentityInfo
from claude_statusbar.styles import render_identity_line
from claude_statusbar.themes import get_theme

THEME = get_theme("graphite")


# --- parser (pure, no subprocess) ----------------------------------------
def test_parse_ahead_and_behind_and_dirty():
    out = "## main...origin/main [ahead 2, behind 1]\n M src/a.py\n?? new.txt\n"
    assert parse_git_status_branch(out) == (True, 2, 1)


def test_parse_in_sync_clean():
    out = "## main...origin/main\n"
    assert parse_git_status_branch(out) == (False, 0, 0)


def test_parse_no_upstream_gives_none_counts():
    out = "## main\n"
    assert parse_git_status_branch(out) == (False, None, None)


def test_parse_behind_only():
    out = "## main...origin/main [behind 3]\n"
    assert parse_git_status_branch(out) == (False, 0, 3)


def test_parse_ahead_only_dirty():
    out = "## main...origin/main [ahead 5]\n?? x\n"
    assert parse_git_status_branch(out) == (True, 5, 0)


# --- render_identity_line ahead/behind -----------------------------------
def _id(**kw):
    base = dict(project_name="p", in_git=True, branch="main", detached=False,
                worktree_name=None, toplevel="/x")
    base.update(kw)
    return IdentityInfo(**base)


def test_render_shows_ahead_behind():
    s = render_identity_line(_id(), theme=THEME, dirty=False,
                             ahead=2, behind=1, use_color=False)
    assert "↑2" in s and "↓1" in s


def test_render_in_sync_no_arrows():
    s = render_identity_line(_id(), theme=THEME, dirty=False,
                             ahead=0, behind=0, use_color=False)
    assert "↑" not in s and "↓" not in s


def test_render_ahead_only():
    s = render_identity_line(_id(), theme=THEME, dirty=False,
                             ahead=3, behind=0, use_color=False)
    assert "↑3" in s and "↓" not in s


def test_render_none_counts_no_arrows():
    s = render_identity_line(_id(), theme=THEME, dirty=False,
                             ahead=None, behind=None, use_color=False)
    assert "↑" not in s and "↓" not in s


def test_render_no_arrows_when_not_in_git():
    s = render_identity_line(_id(in_git=False, branch=None), theme=THEME,
                             dirty=None, ahead=2, behind=0, use_color=False)
    assert "↑" not in s  # no branch → no ahead/behind
