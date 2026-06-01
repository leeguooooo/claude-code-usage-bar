"""Transcript reverse-tail scanner tests (read_activity)."""

import json
from datetime import datetime, timedelta, timezone

from claude_statusbar.activity import read_activity, format_cache_countdown


def _write_jsonl(path, entries):
    path.write_text(
        "\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8"
    )
    return str(path)


def _assistant(ts, blocks):
    return {"type": "assistant", "timestamp": ts,
            "message": {"role": "assistant", "content": blocks}}


def _user_result(ts, tool_use_id, is_error=None):
    return {"type": "user", "timestamp": ts,
            "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": tool_use_id,
                 "is_error": is_error, "content": "ok"}]}}


def _todo_block(tid, todos):
    return {"type": "tool_use", "id": tid, "name": "TodoWrite",
            "input": {"todos": todos}}


# --- todos ----------------------------------------------------------------
def test_todos_parsed_from_todowrite(tmp_path):
    f = _write_jsonl(tmp_path / "t.jsonl", [
        _assistant("2026-06-01T12:00:00Z", [_todo_block("t1", [
            {"content": "Build A", "status": "completed"},
            {"content": "Build B", "status": "in_progress"},
            {"content": "Build C", "status": "pending"},
        ])]),
    ])
    info = read_activity(f)
    assert info.todos == [("Build A", "completed"),
                          ("Build B", "in_progress"),
                          ("Build C", "pending")]
    assert info.todos_total == 3
    assert info.todos_done == 1


def test_newest_todowrite_wins(tmp_path):
    f = _write_jsonl(tmp_path / "t.jsonl", [
        _assistant("2026-06-01T12:00:00Z", [_todo_block("t1", [
            {"content": "A", "status": "pending"}])]),
        _assistant("2026-06-01T12:05:00Z", [_todo_block("t2", [
            {"content": "A", "status": "completed"},
            {"content": "B", "status": "in_progress"}])]),
    ])
    info = read_activity(f)
    # Latest list (2 items, 1 done) — not the stale single-item list.
    assert info.todos_total == 2
    assert info.todos_done == 1
    assert info.in_progress_todo == "B"


def test_no_todowrite_means_no_todos(tmp_path):
    f = _write_jsonl(tmp_path / "t.jsonl", [
        _assistant("2026-06-01T12:00:00Z", [
            {"type": "text", "text": "hi"}]),
    ])
    info = read_activity(f)
    assert info.todos == []
    assert info.todos_total == 0


def test_missing_file_returns_empty(tmp_path):
    info = read_activity(str(tmp_path / "nope.jsonl"))
    assert info.todos == []
    assert info.active_tool is None


# --- active tool ----------------------------------------------------------
def _tool_use(tid, name, inp):
    return {"type": "tool_use", "id": tid, "name": name, "input": inp}


def test_running_tool_is_active(tmp_path):
    # tool_use with no matching tool_result → still running.
    f = _write_jsonl(tmp_path / "t.jsonl", [
        _assistant("2026-06-01T12:00:00Z",
                   [_tool_use("e1", "Edit", {"file_path": "/x/auth.py"})]),
    ])
    info = read_activity(f)
    assert info.active_tool == ("Edit", "auth.py")


def test_completed_tool_not_active_and_counted(tmp_path):
    f = _write_jsonl(tmp_path / "t.jsonl", [
        _assistant("2026-06-01T12:00:00Z",
                   [_tool_use("r1", "Read", {"file_path": "/x/a.py"})]),
        _user_result("2026-06-01T12:00:01Z", "r1"),
    ])
    info = read_activity(f)
    assert info.active_tool is None
    assert info.completed_counts == [("Read", 1)]


def test_completed_rollup_counts_by_name(tmp_path):
    f = _write_jsonl(tmp_path / "t.jsonl", [
        _assistant("2026-06-01T12:00:00Z",
                   [_tool_use("r1", "Read", {"file_path": "/x/a.py"})]),
        _user_result("2026-06-01T12:00:01Z", "r1"),
        _assistant("2026-06-01T12:00:02Z",
                   [_tool_use("r2", "Read", {"file_path": "/x/b.py"})]),
        _user_result("2026-06-01T12:00:03Z", "r2"),
        _assistant("2026-06-01T12:00:04Z",
                   [_tool_use("g1", "Grep", {"pattern": "x"})]),
        _user_result("2026-06-01T12:00:05Z", "g1"),
    ])
    info = read_activity(f)
    # Most frequent first.
    assert info.completed_counts[0] == ("Read", 2)
    assert ("Grep", 1) in info.completed_counts


def test_newest_running_tool_wins(tmp_path):
    f = _write_jsonl(tmp_path / "t.jsonl", [
        _assistant("2026-06-01T12:00:00Z",
                   [_tool_use("b1", "Bash", {"command": "make"})]),
        _assistant("2026-06-01T12:00:05Z",
                   [_tool_use("e1", "Edit", {"file_path": "/x/late.py"})]),
    ])
    info = read_activity(f)
    assert info.active_tool == ("Edit", "late.py")


def test_active_tool_mcp_name_shortened(tmp_path):
    f = _write_jsonl(tmp_path / "t.jsonl", [
        _assistant("2026-06-01T12:00:00Z",
                   [_tool_use("m1", "mcp__figma__get_screenshot", {})]),
    ])
    info = read_activity(f)
    assert info.active_tool[0] == "get_screenshot"


def test_todowrite_excluded_from_tool_rollup(tmp_path):
    f = _write_jsonl(tmp_path / "t.jsonl", [
        _assistant("2026-06-01T12:00:00Z", [_todo_block("t1", [
            {"content": "A", "status": "pending"}])]),
        _user_result("2026-06-01T12:00:01Z", "t1"),
    ])
    info = read_activity(f)
    assert info.completed_counts == []
    assert info.active_tool is None


# --- agents ---------------------------------------------------------------
NOW = datetime(2026, 6, 1, 12, 2, 15, tzinfo=timezone.utc)


def _agent_use(tid, subagent_type, desc, *, model=None, background=False):
    inp = {"subagent_type": subagent_type, "description": desc}
    if model:
        inp["model"] = model
    if background:
        inp["run_in_background"] = True
    return {"type": "tool_use", "id": tid, "name": "Task", "input": inp}


def _queue_enqueue(ts, tool_use_id):
    return {"type": "queue-operation", "operation": "enqueue", "timestamp": ts,
            "content": f"<task-notification>\n<task-id>abc</task-id>\n"
                       f"<tool-use-id>{tool_use_id}</tool-use-id>\n"}


def test_running_inline_agent_with_elapsed(tmp_path):
    f = _write_jsonl(tmp_path / "t.jsonl", [
        _assistant("2026-06-01T12:00:00Z",
                   [_agent_use("a1", "explore", "Find auth code", model="haiku")]),
    ])
    info = read_activity(f, now=NOW)
    assert len(info.agents) == 1
    ag = info.agents[0]
    assert ag["name"] == "explore"
    assert ag["description"] == "Find auth code"
    assert ag["model"] == "haiku"
    assert 130 <= ag["elapsed_seconds"] <= 140  # ~135s


def test_completed_inline_agent_not_shown(tmp_path):
    f = _write_jsonl(tmp_path / "t.jsonl", [
        _assistant("2026-06-01T12:00:00Z",
                   [_agent_use("a1", "explore", "x")]),
        _user_result("2026-06-01T12:01:00Z", "a1"),
    ])
    info = read_activity(f, now=NOW)
    assert info.agents == []


def test_background_agent_completed_via_queue_op(tmp_path):
    f = _write_jsonl(tmp_path / "t.jsonl", [
        _assistant("2026-06-01T12:00:00Z",
                   [_agent_use("a1", "codex", "Review", background=True)]),
        _queue_enqueue("2026-06-01T12:01:30Z", "a1"),
    ])
    info = read_activity(f, now=NOW)
    assert info.agents == []  # enqueue notification means it finished


def test_background_agent_still_running(tmp_path):
    f = _write_jsonl(tmp_path / "t.jsonl", [
        _assistant("2026-06-01T12:00:00Z",
                   [_agent_use("a1", "codex", "Review", background=True)]),
    ])
    info = read_activity(f, now=NOW)
    assert len(info.agents) == 1
    assert info.agents[0]["name"] == "codex"
    assert info.agents[0]["background"] is True


def test_background_agent_with_launch_ack_still_running(tmp_path):
    # A run_in_background dispatch returns an IMMEDIATE tool_result (the
    # "launched successfully" ack). That ack must NOT mark the agent finished
    # — only the later queue-op task-notification does.
    f = _write_jsonl(tmp_path / "t.jsonl", [
        _assistant("2026-06-01T12:00:00Z",
                   [_agent_use("a1", "explore", "scan repo", background=True)]),
        _user_result("2026-06-01T12:00:01Z", "a1"),  # launch ack, NOT completion
    ])
    info = read_activity(f, now=NOW)
    assert len(info.agents) == 1
    assert info.agents[0]["name"] == "explore"


def test_background_agent_done_when_launch_ack_and_queue_op(tmp_path):
    # Realistic completed case: launch ack + the task-notification queue-op.
    f = _write_jsonl(tmp_path / "t.jsonl", [
        _assistant("2026-06-01T12:00:00Z",
                   [_agent_use("a1", "explore", "scan repo", background=True)]),
        _user_result("2026-06-01T12:00:01Z", "a1"),     # launch ack
        _queue_enqueue("2026-06-01T12:01:30Z", "a1"),   # real completion
    ])
    info = read_activity(f, now=NOW)
    assert info.agents == []


def test_agents_not_counted_as_tools(tmp_path):
    f = _write_jsonl(tmp_path / "t.jsonl", [
        _assistant("2026-06-01T12:00:00Z",
                   [_agent_use("a1", "explore", "x")]),
    ])
    info = read_activity(f, now=NOW)
    assert info.active_tool is None
    assert info.completed_counts == []


# --- malformed-input robustness (must never blank the whole bar) ----------
def test_non_dict_todowrite_input_no_crash(tmp_path):
    f = _write_jsonl(tmp_path / "t.jsonl", [
        _assistant("2026-06-01T12:00:00Z", [
            {"type": "tool_use", "id": "t1", "name": "TodoWrite",
             "input": "oops"}]),
    ])
    info = read_activity(f)  # must not raise
    assert info.todos == []


def test_non_dict_agent_input_no_crash(tmp_path):
    f = _write_jsonl(tmp_path / "t.jsonl", [
        _assistant("2026-06-01T12:00:00Z", [
            {"type": "tool_use", "id": "a1", "name": "Task",
             "input": "oops"}]),
    ])
    info = read_activity(f, now=NOW)  # must not raise
    assert isinstance(info.agents, list)


def test_running_tool_non_string_path_no_crash(tmp_path):
    f = _write_jsonl(tmp_path / "t.jsonl", [
        _assistant("2026-06-01T12:00:00Z", [
            {"type": "tool_use", "id": "e1", "name": "Edit",
             "input": {"file_path": 12345}}]),
    ])
    info = read_activity(f)  # must not raise
    assert info.active_tool == ("Edit", "")


def test_non_string_timestamp_no_crash(tmp_path):
    f = _write_jsonl(tmp_path / "t.jsonl", [
        {"type": "assistant", "timestamp": 1234567890,
         "message": {"role": "assistant", "content": [
             {"type": "tool_use", "id": "a1", "name": "Task",
              "input": {"subagent_type": "x", "description": "y"}}]}},
    ])
    info = read_activity(f, now=NOW)  # must not raise
    assert isinstance(info.agents, list)


# --- merged cache-age (one scan covers both cache countdown + activity) ---
def _assistant_usage(ts, ttl_bucket):
    """assistant entry with a cache-creation TTL bucket in message.usage."""
    return {"type": "assistant", "timestamp": ts,
            "message": {"role": "assistant", "content": [],
                        "usage": {"cache_creation": {ttl_bucket: 5}}}}


def test_read_activity_extracts_cache_age_and_ttl(tmp_path):
    ts = (NOW - timedelta(seconds=100)).isoformat()
    f = _write_jsonl(tmp_path / "t.jsonl", [
        _assistant_usage(ts, "ephemeral_1h_input_tokens"),
    ])
    info = read_activity(f, now=NOW)
    assert 95 <= info.cache_age_seconds <= 105
    assert info.cache_ttl == 3600


def test_read_activity_cache_age_none_without_assistant(tmp_path):
    f = _write_jsonl(tmp_path / "t.jsonl", [
        {"type": "user", "timestamp": NOW.isoformat(),
         "message": {"role": "user", "content": []}},
    ])
    info = read_activity(f, now=NOW)
    assert info.cache_age_seconds is None
    assert info.cache_ttl is None


def test_format_cache_countdown_matches_get_cache_age_text():
    assert format_cache_countdown(130, 300) == "2m50s"
    assert format_cache_countdown(None, 300) == "COLD"
    assert format_cache_countdown(400, 300) == "COLD"      # expired
    assert format_cache_countdown(10, 7200) == "1h59m50s"
    assert format_cache_countdown(280, 300) == "20s"       # sub-minute, no 'm'
    assert format_cache_countdown(-50, None) == "5m00s"    # clamp future + 300 fallback
    assert format_cache_countdown(600, 300, ttl_override=3600) == "50m00s"
