"""Config flags for the live-activity / session-stats segments."""

from claude_statusbar.config import StatusbarConfig, load_config, set_value


def test_defaults():
    cfg = StatusbarConfig()
    assert cfg.show_todos is True          # the one most users want
    assert cfg.show_tools is False
    assert cfg.show_tool_rollup is False
    assert cfg.show_agents is False
    assert cfg.show_duration is False
    assert cfg.show_lines is False
    assert cfg.show_ahead_behind is False


def test_set_and_load_roundtrip(tmp_path):
    p = tmp_path / "cfg.json"
    set_value("show_tools", "true", p)
    set_value("show_todos", "false", p)
    set_value("show_ahead_behind", "yes", p)
    cfg = load_config(p)
    assert cfg.show_tools is True
    assert cfg.show_todos is False
    assert cfg.show_ahead_behind is True


def test_load_ignores_unknown_and_keeps_defaults(tmp_path):
    p = tmp_path / "cfg.json"
    p.write_text('{"show_agents": true}', encoding="utf-8")
    cfg = load_config(p)
    assert cfg.show_agents is True
    assert cfg.show_todos is True  # untouched default
