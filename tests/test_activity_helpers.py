"""Pure-helper tests for the live-activity segments (no I/O)."""

from claude_statusbar.activity import (
    extract_target,
    shorten_tool_name,
    format_duration_short,
    format_lines,
    format_elapsed_short,
)


# --- extract_target -------------------------------------------------------
def test_extract_target_read_uses_file_basename():
    assert extract_target("Read", {"file_path": "/Users/leo/proj/auth.py"}) == "auth.py"


def test_extract_target_edit_uses_file_basename():
    assert extract_target("Edit", {"file_path": "/x/y/server.ts"}) == "server.ts"


def test_extract_target_write_falls_back_to_path_key():
    assert extract_target("Write", {"path": "/a/b/c.md"}) == "c.md"


def test_extract_target_grep_uses_pattern():
    assert extract_target("Grep", {"pattern": "TODO"}) == "TODO"


def test_extract_target_glob_uses_pattern():
    assert extract_target("Glob", {"pattern": "**/*.py"}) == "**/*.py"


def test_extract_target_bash_truncates_long_command():
    cmd = "for i in $(seq 1 100); do echo hello world $i; done"
    out = extract_target("Bash", {"command": cmd})
    assert out.startswith("for i in")
    assert out.endswith("…")
    assert len(out) <= 31  # 30 chars + ellipsis


def test_extract_target_bash_short_command_kept_whole():
    assert extract_target("Bash", {"command": "ls -la"}) == "ls -la"


def test_extract_target_skill_uses_skill_name():
    assert extract_target("Skill", {"skill": "superpowers:brainstorming"}) == "superpowers:brainstorming"


def test_extract_target_unknown_tool_is_empty():
    assert extract_target("SomethingElse", {"foo": "bar"}) == ""


def test_extract_target_missing_input_is_empty():
    assert extract_target("Read", {}) == ""


def test_extract_target_non_string_path_no_crash():
    # A malformed transcript could carry a non-string file_path; must not raise.
    assert extract_target("Read", {"file_path": 12345}) == ""
    assert extract_target("Edit", {"file_path": ["/a", "/b"]}) == ""
    assert extract_target("Write", {"path": {"weird": 1}}) == ""


# --- shorten_tool_name ----------------------------------------------------
def test_shorten_mcp_name_keeps_last_segment():
    assert shorten_tool_name("mcp__figma__get_screenshot") == "get_screenshot"


def test_shorten_plain_name_unchanged():
    assert shorten_tool_name("Edit") == "Edit"


def test_shorten_truncates_overlong_name():
    out = shorten_tool_name("a_very_long_tool_name_indeed_yes", max_len=10)
    assert out.endswith("…")
    assert len(out) == 10


def test_shorten_mcp_then_truncate():
    out = shorten_tool_name("mcp__server__an_extremely_long_method_name", max_len=12)
    assert out.endswith("…")
    assert len(out) == 12


# --- format_duration_short ------------------------------------------------
def test_duration_seconds():
    assert format_duration_short(45_000) == "45s"


def test_duration_minutes_drops_seconds():
    assert format_duration_short(12 * 60_000 + 30_000) == "12m"


def test_duration_hours():
    assert format_duration_short(65 * 60_000) == "1h05m"


def test_duration_zero_is_empty():
    assert format_duration_short(0) == ""


# --- format_lines ---------------------------------------------------------
def test_lines_both():
    assert format_lines(182, 47) == "+182 -47"


def test_lines_added_only():
    assert format_lines(5, 0) == "+5"


def test_lines_removed_only():
    assert format_lines(0, 3) == "-3"


def test_lines_none_is_empty():
    assert format_lines(0, 0) == ""


# --- format_elapsed_short -------------------------------------------------
def test_elapsed_sub_second():
    assert format_elapsed_short(0.4) == "<1s"


def test_elapsed_seconds():
    assert format_elapsed_short(45) == "45s"


def test_elapsed_minutes_keeps_seconds():
    assert format_elapsed_short(135) == "2m15s"


def test_elapsed_hours():
    assert format_elapsed_short(3905) == "1h05m"
