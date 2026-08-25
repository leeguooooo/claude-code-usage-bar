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


def test_frozen_upgrade_says_unreachable_not_up_to_date(monkeypatch):
    # A failed PyPI check must never be dressed up as good news — that's how
    # the missing-CA-bundle bug stayed invisible for a month of releases.
    monkeypatch.setattr(updater, "_is_frozen", lambda: True)
    monkeypatch.setattr(updater, "get_current_version", lambda: "3.33.0")
    monkeypatch.setattr(updater, "get_latest_version", lambda: None)

    ok, msg = updater.upgrade_current_install()

    assert ok is False
    assert "could not reach PyPI" in msg
    assert "up to date" not in msg


def test_frozen_upgrade_actually_runs_the_installer(monkeypatch):
    # `cs upgrade` used to print the curl command and exit, so a user who ran
    # it and then checked `cs --version` found nothing had changed.
    monkeypatch.setattr(updater, "_is_frozen", lambda: True)
    monkeypatch.setattr(updater, "get_current_version", lambda: "3.32.5")
    monkeypatch.setattr(updater, "get_latest_version", lambda: "3.33.0")
    ran = []
    monkeypatch.setattr(updater, "_run_installer",
                        lambda v=None: ran.append(v) or True)
    monkeypatch.setattr(updater, "installed_version_on_path", lambda: "3.33.0")

    ok, msg = updater.upgrade_current_install()

    assert ran == ["3.33.0"], "the installer must be pinned to the target tag"
    assert ok is True
    assert "Upgraded" in msg and "3.33.0" in msg


def test_frozen_upgrade_reports_when_a_different_version_landed(monkeypatch):
    # `releases/latest/download` lags after a release: an upgrade to 3.35.3
    # once re-installed 3.35.2 and announced success anyway.
    monkeypatch.setattr(updater, "_is_frozen", lambda: True)
    monkeypatch.setattr(updater, "get_current_version", lambda: "3.35.2")
    monkeypatch.setattr(updater, "get_latest_version", lambda: "3.35.3")
    monkeypatch.setattr(updater, "_run_installer", lambda v=None: True)
    monkeypatch.setattr(updater, "installed_version_on_path", lambda: "3.35.2")

    ok, msg = updater.upgrade_current_install()

    assert ok is False
    assert "3.35.2 is what installed" in msg


def test_frozen_upgrade_failure_hands_back_the_manual_command(monkeypatch):
    monkeypatch.setattr(updater, "_is_frozen", lambda: True)
    monkeypatch.setattr(updater, "get_current_version", lambda: "3.32.5")
    monkeypatch.setattr(updater, "get_latest_version", lambda: "3.33.0")
    monkeypatch.setattr(updater, "_run_installer", lambda v=None: False)

    ok, msg = updater.upgrade_current_install()

    assert ok is False
    assert "install.sh" in msg


def test_frozen_upgrade_does_not_reinstall_when_current(monkeypatch):
    monkeypatch.setattr(updater, "_is_frozen", lambda: True)
    monkeypatch.setattr(updater, "get_current_version", lambda: "3.33.0")
    monkeypatch.setattr(updater, "get_latest_version", lambda: "3.33.0")

    def boom(v=None):
        raise AssertionError("must not re-download when already latest")

    monkeypatch.setattr(updater, "_run_installer", boom)
    ok, msg = updater.upgrade_current_install()

    assert ok is True
    assert "is the latest" in msg


def test_frozen_upgrade_unreachable_pypi_never_runs_the_installer(monkeypatch):
    monkeypatch.setattr(updater, "_is_frozen", lambda: True)
    monkeypatch.setattr(updater, "get_current_version", lambda: "3.33.0")
    monkeypatch.setattr(updater, "get_latest_version", lambda: None)

    def boom(v=None):
        raise AssertionError("never reinstall on a failed version check")

    monkeypatch.setattr(updater, "_run_installer", boom)
    ok, msg = updater.upgrade_current_install()

    assert ok is False
    assert "could not reach PyPI" in msg


def test_pypi_check_bypasses_the_cdn_edge_cache(monkeypatch):
    # pypi.org/pypi/<pkg>/json is CDN-cached; a bare URL can hand back the
    # version you just replaced for minutes after publishing.
    seen = {}

    class _Resp:
        def read(self):
            return b'{"info": {"version": "9.9.9"}}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(url, timeout=None):
        seen["url"] = url
        return _Resp()

    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(updater, "_cache_latest_version", lambda v: None)

    assert updater.get_latest_version() == "9.9.9"
    assert seen["url"].startswith(updater.PYPI_URL + "?")
    assert seen["url"] != updater.PYPI_URL


def test_frozen_auto_upgrade_runs_pinned_and_verifies(monkeypatch):
    # Binary installs auto-upgrade now. The guard that makes that safe is the
    # same one `cs upgrade` uses: pin the download, then check what landed.
    monkeypatch.setattr(updater, "is_shadow_install", lambda: False)
    monkeypatch.setattr(updater, "_is_frozen", lambda: True)
    monkeypatch.setattr(updater, "get_current_version", lambda: "3.35.2")
    monkeypatch.setattr(updater, "get_latest_version", lambda: "3.36.0")
    ran = []
    monkeypatch.setattr(updater, "_run_installer",
                        lambda v=None: ran.append(v) or True)
    monkeypatch.setattr(updater, "installed_version_on_path", lambda: "3.36.0")

    assert updater.auto_upgrade() is True
    assert ran == ["3.36.0"]


def test_frozen_auto_upgrade_reports_failure_when_another_version_lands(monkeypatch):
    monkeypatch.setattr(updater, "is_shadow_install", lambda: False)
    monkeypatch.setattr(updater, "_is_frozen", lambda: True)
    monkeypatch.setattr(updater, "get_current_version", lambda: "3.35.2")
    monkeypatch.setattr(updater, "get_latest_version", lambda: "3.36.0")
    monkeypatch.setattr(updater, "_run_installer", lambda v=None: True)
    monkeypatch.setattr(updater, "installed_version_on_path", lambda: "3.35.2")

    assert updater.auto_upgrade() is False


def test_frozen_auto_upgrade_skips_when_already_current(monkeypatch):
    monkeypatch.setattr(updater, "is_shadow_install", lambda: False)
    monkeypatch.setattr(updater, "_is_frozen", lambda: True)
    monkeypatch.setattr(updater, "get_current_version", lambda: "3.36.0")
    monkeypatch.setattr(updater, "get_latest_version", lambda: "3.36.0")

    def boom(v=None):
        raise AssertionError("no reinstall when already on the latest")

    monkeypatch.setattr(updater, "_run_installer", boom)
    assert updater.auto_upgrade() is False


def test_frozen_auto_upgrade_still_refuses_to_hijack(monkeypatch):
    monkeypatch.setattr(updater, "_is_frozen", lambda: True)
    monkeypatch.setattr(updater, "is_shadow_install", lambda: True)

    def boom(v=None):
        raise AssertionError("a shadow install must never upgrade itself")

    monkeypatch.setattr(updater, "_run_installer", boom)
    assert updater.auto_upgrade() is False


def test_installer_spares_the_bundle_it_is_running_from(monkeypatch, tmp_path):
    # An unattended upgrade executes out of a bundle the installer would
    # otherwise delete out from under it.
    monkeypatch.setattr(updater, "_is_frozen", lambda: True)
    bundle = tmp_path / "v3.35.2-abc"
    bundle.mkdir()
    monkeypatch.setattr(updater.sys, "executable", str(bundle / "cs"))
    seen = {}

    class _R:
        returncode = 0

    def fake_run(cmd, timeout=None, env=None, **kw):
        seen["env"] = env
        return _R()

    monkeypatch.setattr(updater.subprocess, "run", fake_run)
    assert updater._run_installer("3.36.0") is True
    assert seen["env"]["CS_KEEP_BUNDLE_DIR"] == str(bundle)
    assert "releases/download/v3.36.0" in seen["env"]["CS_RELEASE_BASE_URL"]
