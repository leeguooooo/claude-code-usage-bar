import claude_statusbar.updater as updater


def test_detect_install_channel_uv():
    path = "/Users/test/.local/share/uv/tools/claude-statusbar/bin/python"
    assert updater.detect_install_channel(path) == "uv"


def test_detect_install_channel_uv_tool_python_symlink(tmp_path):
    real_python = tmp_path / ".local/share/uv/python/cpython-3.13/bin/python3.13"
    tool_python = tmp_path / ".local/share/uv/tools/claude-statusbar/bin/python3"
    real_python.parent.mkdir(parents=True)
    tool_python.parent.mkdir(parents=True)
    real_python.write_text("", encoding="utf-8")
    tool_python.symlink_to(real_python)

    assert updater.detect_install_channel(tool_python) == "uv"


def test_detect_install_channel_pipx():
    path = "/Users/test/.local/pipx/venvs/claude-statusbar/bin/python"
    assert updater.detect_install_channel(path) == "pipx"


def test_detect_install_channel_falls_back_to_pip():
    path = "/Users/test/miniconda3/bin/python"
    assert updater.detect_install_channel(path) == "pip"


def test_get_upgrade_command_prefers_uv(monkeypatch):
    monkeypatch.setattr(updater.shutil, "which", lambda name: "/usr/bin/uv" if name == "uv" else None)
    cmd = updater.get_upgrade_command(
        "/Users/test/.local/share/uv/tools/claude-statusbar/bin/python"
    )
    assert cmd == ["/usr/bin/uv", "tool", "install", "--upgrade", "claude-statusbar"]


def test_get_upgrade_command_prefers_pipx(monkeypatch):
    monkeypatch.setattr(updater.shutil, "which", lambda name: "/usr/bin/pipx" if name == "pipx" else None)
    cmd = updater.get_upgrade_command(
        "/Users/test/.local/pipx/venvs/claude-statusbar/bin/python"
    )
    assert cmd == ["/usr/bin/pipx", "upgrade", "claude-statusbar"]


def test_get_upgrade_command_falls_back_to_pip(monkeypatch):
    monkeypatch.setattr(updater.shutil, "which", lambda name: None)
    cmd = updater.get_upgrade_command("/Users/test/miniconda3/bin/python")
    assert cmd == [updater.sys.executable, "-m", "pip", "install", "--upgrade", "claude-statusbar"]


def test_uv_found_in_well_known_dir_when_not_on_path(monkeypatch, tmp_path):
    """launchd/systemd run the daemon with the bare system PATH, which lacks
    ~/.local/bin — so `shutil.which("uv")` fails there even though uv is
    installed. The old code then fell back to `python -m pip`, and a uv tool
    venv has NO pip: the daemon's auto-upgrade failed silently, forever.
    Well-known tool dirs must be searched after PATH."""
    fake_uv = tmp_path / "uv"
    fake_uv.write_text("#!/bin/sh\n")
    monkeypatch.setattr(updater.shutil, "which", lambda name: None)  # launchd PATH
    monkeypatch.setattr(updater, "_TOOL_DIRS", (tmp_path,))
    cmd = updater.get_upgrade_command(
        "/Users/test/.local/share/uv/tools/claude-statusbar/bin/python"
    )
    assert cmd == [str(fake_uv), "tool", "install", "--upgrade", "claude-statusbar"]


def test_uv_channel_without_uv_anywhere_falls_back_to_pip(monkeypatch):
    monkeypatch.setattr(updater.shutil, "which", lambda name: None)
    monkeypatch.setattr(updater, "_TOOL_DIRS", ())
    cmd = updater.get_upgrade_command(
        "/Users/test/.local/share/uv/tools/claude-statusbar/bin/python"
    )
    assert cmd[0] == updater.sys.executable


# ---------------------------------------------------------------------------
# Reliability: subprocess timeout MUST be enforced so a hung pip/uv install
# can never freeze the Claude Code statusLine render.
# ---------------------------------------------------------------------------
import subprocess


def test_run_upgrade_passes_timeout(monkeypatch):
    """_run_upgrade must always pass a timeout kwarg to subprocess.run."""
    captured = {}

    class FakeResult:
        returncode = 0

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return FakeResult()

    monkeypatch.setattr(updater.subprocess, "run", fake_run)
    updater._run_upgrade(["echo", "hi"])
    assert "timeout" in captured
    assert captured["timeout"] == updater._UPGRADE_TIMEOUT_S


def test_run_upgrade_returns_false_on_timeout(monkeypatch):
    def hang(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout", 0))

    monkeypatch.setattr(updater.subprocess, "run", hang)
    assert updater._run_upgrade(["pip", "install", "x"]) is False


def test_run_upgrade_returns_false_on_oserror(monkeypatch):
    def boom(*args, **kwargs):
        raise FileNotFoundError("no such binary")

    monkeypatch.setattr(updater.subprocess, "run", boom)
    assert updater._run_upgrade(["nonexistent-tool"]) is False


def test_auto_upgrade_falls_through_to_pip(monkeypatch):
    """When primary and pipx upgrades fail, auto_upgrade must still try pip
    rather than re-raising or hanging."""
    calls = []

    class FakeResult:
        def __init__(self, rc): self.returncode = rc

    def fake_run(cmd, **kwargs):
        calls.append(cmd[0])
        return FakeResult(1)  # always fail

    monkeypatch.setattr(updater.subprocess, "run", fake_run)
    monkeypatch.setattr(updater.shutil, "which", lambda name: "/usr/bin/pipx" if name == "pipx" else None)

    assert updater.auto_upgrade() is False
    # Must have attempted pip after the others failed
    assert any("python" in c or c == "pip" or "/python" in c for c in calls), \
        f"auto_upgrade did not fall through to pip: {calls}"


def test_upgrade_current_install_reports_manual_command(monkeypatch):
    monkeypatch.setattr(updater, "get_current_version", lambda: "3.26.0")
    monkeypatch.setattr(
        updater,
        "get_upgrade_command",
        lambda: ["uv", "tool", "install", "--upgrade", "claude-statusbar"],
    )
    monkeypatch.setattr(updater, "_run_upgrade", lambda cmd: False)

    ok, msg = updater.upgrade_current_install()

    assert ok is False
    assert "uv tool install --upgrade claude-statusbar" in msg
