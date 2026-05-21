from claude_statusbar.identity import IdentityInfo
from claude_statusbar.styles import render_identity_line
from claude_statusbar.themes import get_theme


THEME = get_theme("graphite")


def test_with_branch_and_clean():
    s = render_identity_line(
        IdentityInfo(project_name="proj", in_git=True, branch="main",
                     detached=False, worktree_name=None, toplevel="/x"),
        theme=THEME, dirty=False, use_color=False,
    )
    assert "proj" in s
    assert "main" in s
    assert "●" not in s  # ●
    assert "⤷" in s  # ⤷
    assert "⎇" in s  # ⎇


def test_with_branch_and_dirty():
    s = render_identity_line(
        IdentityInfo(project_name="proj", in_git=True, branch="main",
                     detached=False, worktree_name=None, toplevel="/x"),
        theme=THEME, dirty=True, use_color=False,
    )
    assert "●" in s


def test_no_git_shows_no_git_tag():
    s = render_identity_line(
        IdentityInfo(project_name="proj", in_git=False, branch=None,
                     detached=False, worktree_name=None, toplevel=None),
        theme=THEME, dirty=None, use_color=False,
    )
    assert "(no git)" in s
    assert "⎇" not in s


def test_detached_head_uses_short_sha():
    s = render_identity_line(
        IdentityInfo(project_name="proj", in_git=True, branch="abc1234",
                     detached=True, worktree_name=None, toplevel="/x"),
        theme=THEME, dirty=False, use_color=False,
    )
    assert "abc1234" in s


def test_worktree_suffix():
    s = render_identity_line(
        IdentityInfo(project_name="proj", in_git=True, branch="feat-x",
                     detached=False, worktree_name="feat-x", toplevel="/x"),
        theme=THEME, dirty=False, use_color=False,
    )
    assert "feat-x" in s
    assert "worktree" in s.lower()


def test_color_mode_emits_ansi():
    s = render_identity_line(
        IdentityInfo(project_name="proj", in_git=True, branch="main",
                     detached=False, worktree_name=None, toplevel="/x"),
        theme=THEME, dirty=True, use_color=True,
    )
    assert "\x1b[" in s
