"""Severity thresholds must resolve explicit-arg → config → default on the
render path.

Regression: core.main() hardcoded 30/70 and never read cfg.warning_threshold /
cfg.critical_threshold, so `cs config set warning_threshold 55` validated, saved,
and showed in `cs config show` but silently never affected the bar.
"""

import io
import json
import sys

import claude_statusbar.config as config
import claude_statusbar.progress as progress
from claude_statusbar.core import main


def _payload():
    return json.dumps({
        "session_id": "t",
        "model": {"id": "o", "display_name": "Opus"},
        "rate_limits": {
            "five_hour": {"used_percentage": 42, "resets_at": 9999999999},
            "seven_day": {"used_percentage": 10, "resets_at": 9999999999},
        },
        "context_window": {"used_percentage": 20, "context_window_size": 1000000,
                           "total_input_tokens": 200000},
    })


def _run_capture(tmp_path, monkeypatch, cfg_values, **main_kwargs):
    """Render once and capture the thresholds main() actually passed down."""
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".claude").mkdir(parents=True)
    cfg_path = tmp_path / ".claude" / "claude-statusbar.json"
    base = {"show_project_branch": False, "show_cache_age": False,
            "show_todos": False, "show_mode": False}
    base.update(cfg_values)
    cfg_path.write_text(json.dumps(base), encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", cfg_path)

    captured = {}
    real = progress.format_status_line

    def spy(*a, **k):
        captured["warn"] = k.get("warning_threshold")
        captured["crit"] = k.get("critical_threshold")
        return real(*a, **k)

    monkeypatch.setattr(progress, "format_status_line", spy)
    monkeypatch.setattr(sys, "stdin", io.StringIO(_payload()))
    main(use_color=False, style_override="classic",
         _suppress_side_effects=True, **main_kwargs)
    return captured


def test_config_thresholds_drive_render(tmp_path, monkeypatch):
    cap = _run_capture(tmp_path, monkeypatch,
                       {"warning_threshold": 55.0, "critical_threshold": 65.0})
    assert cap["warn"] == 55.0
    assert cap["crit"] == 65.0


def test_explicit_arg_overrides_config(tmp_path, monkeypatch):
    cap = _run_capture(tmp_path, monkeypatch,
                       {"warning_threshold": 55.0, "critical_threshold": 65.0},
                       warning_threshold=20.0, critical_threshold=40.0)
    assert cap["warn"] == 20.0
    assert cap["crit"] == 40.0


def test_default_thresholds_when_unset(tmp_path, monkeypatch):
    cap = _run_capture(tmp_path, monkeypatch, {})
    assert cap["warn"] == 30.0
    assert cap["crit"] == 70.0
