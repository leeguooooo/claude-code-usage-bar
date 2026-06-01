"""`cs config show` must list every togglable key, including the identity /
activity flags (regression: the display list was hardcoded and omitted them)."""

import sys

from claude_statusbar import cli


def test_config_show_lists_all_show_flags(capsys, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["cs", "config", "show"])
    rc = cli.main()
    out = capsys.readouterr().out
    assert rc == 0
    for key in ("show_project_branch", "show_ahead_behind", "show_todos",
                "show_tools", "show_tool_rollup", "show_agents",
                "show_duration", "show_lines"):
        assert key in out, f"{key} missing from `cs config show`"
