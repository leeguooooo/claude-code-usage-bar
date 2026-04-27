"""`cs doctor` self-diagnostic — must not crash on any combination of
missing/corrupt files. Users running it are exactly the ones with
broken environments, so robustness > completeness."""

import json
from pathlib import Path

import pytest

from claude_statusbar import doctor


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    """Redirect every state file the doctor reads into a clean tmpdir."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


def test_doctor_runs_clean_when_nothing_exists(capsys, _isolated):
    """No settings.json, no cache, no config — every line should still
    render without raising."""
    rc = doctor.run()
    assert rc == 0
    out = capsys.readouterr().out
    assert "cs doctor" in out
    assert "version" in out


def test_doctor_runs_when_settings_is_corrupt(capsys, _isolated):
    """Corrupt settings.json should be flagged, not crash."""
    p = _isolated / ".claude" / "settings.json"
    p.parent.mkdir(parents=True)
    p.write_text("{ broken json", encoding="utf-8")
    assert doctor.run() == 0
    out = capsys.readouterr().out
    assert "settings.json" in out or "statusLine" in out


def test_doctor_recognizes_our_statusline(capsys, _isolated):
    p = _isolated / ".claude" / "settings.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({
        "statusLine": {"type": "command", "command": "/path/to/cs"}
    }), encoding="utf-8")
    doctor.run()
    out = capsys.readouterr().out
    assert "(ours)" in out


def test_doctor_flags_foreign_statusline(capsys, _isolated):
    p = _isolated / ".claude" / "settings.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({
        "statusLine": {"type": "command", "command": "starship"}
    }), encoding="utf-8")
    doctor.run()
    out = capsys.readouterr().out
    assert "(not ours)" in out


def test_doctor_reports_cache_age(capsys, _isolated):
    """Fresh cache → 'Ns ago'."""
    p = _isolated / ".cache" / "claude-statusbar" / "last_stdin.json"
    p.parent.mkdir(parents=True)
    p.write_text("{}", encoding="utf-8")
    doctor.run()
    out = capsys.readouterr().out
    assert "ago" in out


def test_doctor_lists_installed_slash_commands(capsys, _isolated):
    cmds = _isolated / ".claude" / "commands"
    cmds.mkdir(parents=True)
    for name in ("statusbar.md", "statusbar-style.md", "other-thing.md"):
        (cmds / name).write_text("---\n", encoding="utf-8")
    doctor.run()
    out = capsys.readouterr().out
    # Counts only statusbar*.md
    assert "2 installed" in out
    assert "statusbar.md" in out
    assert "statusbar-style.md" in out
    assert "other-thing.md" not in out
