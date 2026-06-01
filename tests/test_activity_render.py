"""Rendering of the optional 3rd 'activity' line + dispatcher wiring."""

from claude_statusbar.activity import ActivityInfo
from claude_statusbar.styles import render_activity_line, render, render_agent_lines
from claude_statusbar.themes import get_theme

THEME = get_theme("graphite")


def _line(**kw):
    kw.setdefault("use_color", False)
    kw.setdefault("theme", THEME)
    return render_activity_line(**kw)


def _agents(agents):
    return render_agent_lines(agents, theme=THEME, use_color=False)


# --- todos ----------------------------------------------------------------
def test_todos_shows_in_progress_task_and_count():
    info = ActivityInfo(todos=[("Build A", "completed"),
                               ("Build B", "in_progress"),
                               ("Build C", "pending")])
    s = _line(activity=info, show_todos=True)
    assert "Build B" in s
    assert "1/3" in s
    assert "▸" in s


def test_todos_without_in_progress_shows_label():
    info = ActivityInfo(todos=[("A", "completed"), ("B", "pending")])
    s = _line(activity=info, show_todos=True)
    assert "1/2" in s


def test_todos_hidden_when_flag_off():
    info = ActivityInfo(todos=[("A", "in_progress")])
    s = _line(activity=info, show_todos=False)
    assert "A" not in s


# --- active tool + rollup -------------------------------------------------
def test_active_tool_rendered():
    info = ActivityInfo(active_tool=("Edit", "auth.py"))
    s = _line(activity=info, show_tools=True)
    assert "Edit" in s and "auth.py" in s
    assert "◐" in s


def test_completed_rollup_rendered():
    info = ActivityInfo(completed_counts=[("Read", 3), ("Bash", 1)])
    s = _line(activity=info, show_tool_rollup=True)
    assert "Read" in s and "3" in s
    assert "✓" in s


def test_rollup_gated_by_its_own_flag_not_show_tools():
    # show_tools controls the active tool; the rollup needs show_tool_rollup.
    info = ActivityInfo(active_tool=("Edit", "auth.py"),
                        completed_counts=[("Read", 3)])
    s = _line(activity=info, show_tools=True)          # rollup flag OFF
    assert "Edit" in s          # active tool shows
    assert "✓" not in s         # rollup hidden
    assert "Read" not in s


def test_tools_hidden_when_flag_off():
    info = ActivityInfo(active_tool=("Edit", "auth.py"))
    s = _line(activity=info, show_tools=False)
    assert "Edit" not in s


# --- agents (their own bottom line(s), one per agent) ---------------------
def test_agent_line_with_model_and_elapsed():
    lines = _agents([{"name": "explore", "model": "haiku", "description": "x",
                      "elapsed_seconds": 135, "background": False}])
    assert len(lines) == 1
    assert "explore" in lines[0] and "haiku" in lines[0] and "2m15s" in lines[0]
    assert "◐" in lines[0]


def test_agent_line_without_model():
    lines = _agents([{"name": "codex", "model": "", "description": "x",
                      "elapsed_seconds": 5, "background": True}])
    assert "codex" in lines[0] and "5s" in lines[0]


def test_agent_line_shows_description():
    lines = _agents([{"name": "explore", "model": "haiku",
                      "description": "探索 RsaKeyPairPool", "elapsed_seconds": 30,
                      "background": False}])
    assert "探索 RsaKeyPairPool" in lines[0]


def test_agent_line_long_description_truncated():
    long = ("do a very long task description that should certainly be cut off "
            "somewhere well before this whole sentence ever ends here")
    lines = _agents([{"name": "a", "model": "", "description": long,
                      "elapsed_seconds": 1, "background": False}])
    assert "…" in lines[0]
    assert long not in lines[0]


def test_no_agents_no_lines():
    assert _agents([]) == []


def test_multiple_agents_multiple_lines():
    lines = _agents([
        {"name": "explore", "model": "haiku", "description": "a",
         "elapsed_seconds": 10, "background": True},
        {"name": "codex", "model": "", "description": "b",
         "elapsed_seconds": 20, "background": True},
    ])
    assert len(lines) == 2
    assert "explore" in lines[0]
    assert "codex" in lines[1]


def test_agents_not_on_activity_line():
    # The activity line no longer carries agents — they get their own lines.
    info = ActivityInfo(active_tool=("Edit", "x.py"),
                        agents=[{"name": "explore", "model": "", "description": "d",
                                 "elapsed_seconds": 5, "background": True}])
    s = _line(activity=info, show_todos=True, show_tools=True)
    assert "explore" not in s
    assert "Edit" in s  # tools still on the activity line


# Session stats (duration / lines) moved to the identity line —
# see test_project_branch_render.py.


# --- empty / color --------------------------------------------------------
def test_empty_returns_blank():
    s = _line(activity=ActivityInfo(), show_todos=True, show_tools=True)
    assert s == ""


def test_color_mode_emits_ansi():
    info = ActivityInfo(todos=[("A", "in_progress")])
    s = render_activity_line(activity=info, theme=THEME, use_color=True,
                             show_todos=True)
    assert "\x1b[" in s


# --- dispatcher -----------------------------------------------------------
def test_dispatcher_appends_activity_line():
    info = ActivityInfo(todos=[("Ship it", "in_progress")])
    out = render("classic", msgs_pct=10, weekly_pct=20, model="Opus 4.7",
                 reset_5h="4h", reset_7d="6d", use_color=False, theme=THEME,
                 activity=info, activity_opts={"show_todos": True})
    assert "\n" in out
    assert "Ship it" in out.split("\n", 1)[1]


def test_dispatcher_no_activity_line_without_opts():
    info = ActivityInfo(todos=[("Ship it", "in_progress")])
    out = render("classic", msgs_pct=10, weekly_pct=20, model="Opus 4.7",
                 reset_5h="4h", reset_7d="6d", use_color=False, theme=THEME,
                 activity=info)
    assert "\n" not in out


def test_dispatcher_activity_after_identity():
    from claude_statusbar.identity import IdentityInfo
    info = ActivityInfo(todos=[("Ship it", "in_progress")])
    out = render("classic", msgs_pct=10, weekly_pct=20, model="Opus 4.7",
                 reset_5h="4h", reset_7d="6d", use_color=False, theme=THEME,
                 show_project_branch=True,
                 identity=IdentityInfo(project_name="demo", in_git=True,
                                       branch="main", detached=False,
                                       worktree_name=None, toplevel="/x"),
                 identity_dirty=False,
                 activity=info, activity_opts={"show_todos": True})
    lines = out.split("\n")
    assert len(lines) == 3
    assert "demo" in lines[1]      # identity is 2nd
    assert "Ship it" in lines[2]   # activity is 3rd


def test_dispatcher_agents_on_their_own_bottom_lines():
    info = ActivityInfo(
        todos=[("task", "in_progress")],
        agents=[{"name": "explore", "model": "haiku", "description": "d",
                 "elapsed_seconds": 5, "background": True},
                {"name": "codex", "model": "", "description": "e",
                 "elapsed_seconds": 6, "background": True}])
    out = render("classic", msgs_pct=10, weekly_pct=20, model="Opus",
                 reset_5h="4h", reset_7d="6d", use_color=False, theme=THEME,
                 activity=info,
                 activity_opts={"show_todos": True, "show_agents": True})
    lines = out.split("\n")
    # main / activity(todos) / agent1 / agent2
    assert len(lines) == 4
    assert "task" in lines[1] and "explore" not in lines[1]  # agents off activity line
    assert "explore" in lines[2]
    assert "codex" in lines[3]


def test_dispatcher_agents_only_no_activity_line():
    # show_agents on, nothing else → agent line(s) come right after the main line.
    info = ActivityInfo(agents=[{"name": "explore", "model": "", "description": "d",
                                 "elapsed_seconds": 5, "background": True}])
    out = render("classic", msgs_pct=10, weekly_pct=20, model="Opus",
                 reset_5h="4h", reset_7d="6d", use_color=False, theme=THEME,
                 activity=info, activity_opts={"show_agents": True})
    lines = out.split("\n")
    assert len(lines) == 2
    assert "explore" in lines[1]
