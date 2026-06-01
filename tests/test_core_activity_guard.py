"""core.main must never blank the whole status bar if the activity scan
raises. read_activity is called before main()'s big try/except, so it needs
its own guard — a scanner bug should degrade to 'no activity line', not a
blank bar."""

import io
import json
import sys


def test_main_survives_activity_scan_exception(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".claude").mkdir(parents=True)
    (tmp_path / ".claude" / "claude-statusbar.json").write_text(
        json.dumps({"show_todos": True, "show_project_branch": False,
                    "show_cache_age": False}),
        encoding="utf-8",
    )

    import claude_statusbar.activity as activity_mod

    def boom(*a, **k):
        raise RuntimeError("scanner blew up")

    monkeypatch.setattr(activity_mod, "read_activity", boom)

    payload = json.dumps({
        "session_id": "x",
        "transcript_path": "/some/transcript.jsonl",  # truthy → scan attempted
        "model": {"id": "claude-opus-4-8", "display_name": "Opus 4.8"},
        "rate_limits": {
            "five_hour": {"used_percentage": 10, "resets_at": 9999999999},
            "seven_day": {"used_percentage": 5, "resets_at": 9999999999}},
    })
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))

    from claude_statusbar.core import main
    main(use_color=False, _suppress_side_effects=True)

    out = capsys.readouterr().out
    # The bar still rendered the main line; it did not blank.
    assert "Opus 4.8" in out
