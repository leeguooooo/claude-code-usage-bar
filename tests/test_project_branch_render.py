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
    # A worktree shows a bare boolean marker — no redundant name, since the
    # branch already identifies which worktree it is.
    s = render_identity_line(
        IdentityInfo(project_name="proj", in_git=True, branch="feat-x",
                     detached=False, worktree_name="feat-x", toplevel="/x",
                     is_worktree=True),
        theme=THEME, dirty=False, use_color=False,
    )
    assert "[worktree]" in s


def test_no_worktree_marker_for_normal_checkout():
    s = render_identity_line(
        IdentityInfo(project_name="proj", in_git=True, branch="main",
                     detached=False, worktree_name=None, toplevel="/x",
                     is_worktree=False),
        theme=THEME, dirty=False, use_color=False,
    )
    assert "worktree" not in s.lower()


def test_color_mode_emits_ansi():
    s = render_identity_line(
        IdentityInfo(project_name="proj", in_git=True, branch="main",
                     detached=False, worktree_name=None, toplevel="/x"),
        theme=THEME, dirty=True, use_color=True,
    )
    assert "\x1b[" in s


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


def test_identity_line_shows_duration_and_lines():
    s = render_identity_line(
        IdentityInfo(project_name="proj", in_git=True, branch="main",
                     detached=False, worktree_name=None, toplevel="/x"),
        theme=THEME, dirty=False, duration_text="1h12m", lines_text="+235",
        use_color=False,
    )
    assert "proj" in s and "main" in s
    assert "⏱" in s and "1h12m" in s
    assert "+235" in s


def test_identity_line_lines_diff_colored():
    s = render_identity_line(
        IdentityInfo(project_name="p", in_git=True, branch="main",
                     detached=False, worktree_name=None, toplevel="/x"),
        theme=THEME, dirty=False, lines_text="+41 -15", use_color=True,
    )
    from claude_statusbar.styles import _fg
    assert _fg(THEME.s_ok) in s    # +41 green
    assert _fg(THEME.s_hot) in s   # -15 red


def test_identity_line_lines_before_duration():
    # Lines (productivity) read first; the weaker duration signal trails it.
    s = render_identity_line(
        IdentityInfo(project_name="p", in_git=True, branch="main",
                     detached=False, worktree_name=None, toplevel="/x"),
        theme=THEME, dirty=False, duration_text="1h12m", lines_text="+235",
        use_color=False,
    )
    assert s.index("+235") < s.index("1h12m")


def test_identity_line_no_stats_when_absent():
    s = render_identity_line(
        IdentityInfo(project_name="p", in_git=True, branch="main",
                     detached=False, worktree_name=None, toplevel="/x"),
        theme=THEME, dirty=False, use_color=False,
    )
    assert "⏱" not in s


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
