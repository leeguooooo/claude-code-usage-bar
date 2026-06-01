"""Color/hierarchy of the activity + identity lines (tweaks A/B/C/D).

Assertions use the same `_fg(theme.*)` the renderer uses, so they pin the
intended color *role* without hardcoding RGB."""

from claude_statusbar.activity import ActivityInfo
from claude_statusbar.identity import IdentityInfo
from claude_statusbar.styles import _fg, render_activity_line, render_identity_line
from claude_statusbar.themes import get_theme

TH = get_theme("graphite")


# A — completed rollup: tool name in ink, ×count in mute
def test_rollup_name_ink_count_mute():
    s = render_activity_line(
        activity=ActivityInfo(completed_counts=[("Bash", 17)]),
        theme=TH, use_color=True, show_tool_rollup=True)
    assert _fg(TH.ink) in s     # the tool name is brightened
    assert _fg(TH.mute) in s    # the count stays muted


# B — lines diff colors (+green/-red) now live on the identity line —
# see test_project_branch_render.test_identity_line_lines_diff_colored.


# C — separators use mute, not the near-invisible edge
def test_separator_is_mute_not_edge():
    s = render_activity_line(
        activity=ActivityInfo(todos=[("a", "in_progress")],
                              active_tool=("Edit", "x.py")),
        theme=TH, use_color=True, show_todos=True, show_tools=True)
    assert _fg(TH.mute) in s
    assert _fg(TH.edge) not in s   # edge no longer used on the activity line


# D — ahead/behind tinted with an accent, not bare mute
def test_ahead_behind_tinted():
    info = IdentityInfo(project_name="p", in_git=True, branch="main",
                        detached=False, worktree_name=None, toplevel="/x")
    s = render_identity_line(info, theme=TH, dirty=False, ahead=2, behind=0,
                             use_color=True)
    assert "↑2" in s
    assert _fg(TH.s_ok) in s    # accent tint, not plain mute
