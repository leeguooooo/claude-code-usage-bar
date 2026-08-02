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


@pytest.fixture(autouse=True)
def _no_real_render(monkeypatch):
    """`cs doctor` shells out to a real `cs render` for its smoke test. Tests
    must never actually spawn it: the child inherits the real HOME (escaping the
    tmp sandbox above) and can lazily start a daemon."""
    import subprocess
    monkeypatch.setattr(
        subprocess, "run",
        lambda argv, **kw: subprocess.CompletedProcess(argv, 0, b"bar", b""))


def test_doctor_runs_clean_when_nothing_exists(capsys, _isolated):
    """No settings.json, no cache, no config — every line should still
    render without raising."""
    rc = doctor.run()
    assert rc == 0
    out = capsys.readouterr().out
    assert "cs doctor" in out
    assert "version" in out
    assert "statusLine shell test" in out
    assert "no statusLine entry recognized as ours" in out


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


# ---------------------------------------------------------------------------
# Render smoke test (issue #36). Every other doctor check inspects state and
# can be green while rendering is dead — this one actually renders.
# ---------------------------------------------------------------------------
def _cache_with_payload(home):
    cache = home / ".cache" / "claude-statusbar" / "last_stdin.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"session_id": "s1"}), encoding="utf-8")
    return cache


def test_smoke_test_reports_ok_when_render_succeeds(capsys, _isolated, monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess, "run",
                        lambda argv, **kw: subprocess.CompletedProcess(argv, 0, b"5h 12%", b""))
    doctor._render_smoke_test(_cache_with_payload(_isolated))
    out = capsys.readouterr().out
    assert "render smoke test" in out and "ok" in out


def test_smoke_test_surfaces_crash(capsys, _isolated, monkeypatch):
    """The exact issue #36 symptom must be reported, not hidden behind green."""
    import subprocess
    tb = (b'Traceback (most recent call last):\n'
          b'  File "claude_statusbar/render_thin.py", line 68, in _pkg_mtime\n'
          b'ValueError: max() iterable argument is empty\n')
    monkeypatch.setattr(subprocess, "run",
                        lambda argv, **kw: subprocess.CompletedProcess(argv, 1, b"", tb))
    doctor._render_smoke_test(_cache_with_payload(_isolated))
    out = capsys.readouterr().out
    assert "CRASHED" in out
    assert "ValueError: max() iterable argument is empty" in out


def test_smoke_test_flags_blank_output(capsys, _isolated, monkeypatch):
    """Exit 0 but nothing rendered still means a blank status line."""
    import subprocess
    monkeypatch.setattr(subprocess, "run",
                        lambda argv, **kw: subprocess.CompletedProcess(argv, 0, b"  \n", b""))
    doctor._render_smoke_test(_cache_with_payload(_isolated))
    assert "rendered nothing" in capsys.readouterr().out


def test_smoke_test_skips_without_cache(capsys, _isolated):
    doctor._render_smoke_test(_isolated / ".cache" / "nope.json")
    assert "skipped" in capsys.readouterr().out


def test_smoke_test_never_raises_when_subprocess_explodes(capsys, _isolated, monkeypatch):
    import subprocess
    def _boom(*a, **kw):
        raise OSError("exec format error")
    monkeypatch.setattr(subprocess, "run", _boom)
    doctor._render_smoke_test(_cache_with_payload(_isolated))
    assert "could not run" in capsys.readouterr().out


def test_render_argv_uses_binary_directly_when_frozen(monkeypatch):
    import sys as _s
    monkeypatch.setattr(_s, "frozen", True, raising=False)
    monkeypatch.setattr(_s, "executable", "/home/u/.local/bin/cs")
    assert doctor._render_argv() == ["/home/u/.local/bin/cs", "render"]


def test_render_argv_uses_dash_m_when_not_frozen(monkeypatch):
    import sys as _s
    monkeypatch.delattr(_s, "frozen", raising=False)
    assert doctor._render_argv()[1:] == ["-m", "claude_statusbar.cli", "render"]


def test_shell_check_uses_patchable_windows_probe(
        capsys, _isolated, monkeypatch):
    from claude_statusbar import setup as setup_mod
    monkeypatch.setattr(setup_mod, "_is_windows", lambda: True)
    doctor._statusline_shell_check(
        r"C:\Users\me\Scripts\cs.EXE", _isolated / "missing.json")
    out = capsys.readouterr().out
    assert "backslash path" in out
    assert "run: cs --setup" in out
