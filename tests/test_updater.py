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

import pytest
import sys


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
        def __init__(self, rc): self.returncode, self.stderr = rc, b""

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
    # A failed version check must never be dressed up as good news — that's
    # how the missing-CA-bundle bug stayed invisible for a month of releases.
    monkeypatch.setattr(updater, "_is_frozen", lambda: True)
    monkeypatch.setattr(updater, "get_current_version", lambda: "3.33.0")
    monkeypatch.setattr(updater, "get_latest_version", lambda: None)
    monkeypatch.setattr(updater, "resolve_latest_version", lambda: None)

    ok, msg = updater.upgrade_current_install()

    assert ok is False
    assert "could not reach GitHub or PyPI" in msg
    assert "up to date" not in msg


def test_frozen_upgrade_actually_runs_the_installer(monkeypatch):
    # `cs upgrade` used to print the curl command and exit, so a user who ran
    # it and then checked `cs --version` found nothing had changed.
    monkeypatch.setattr(updater, "_is_frozen", lambda: True)
    monkeypatch.setattr(updater, "get_current_version", lambda: "3.32.5")
    monkeypatch.setattr(updater, "get_latest_version", lambda: "3.33.0")
    monkeypatch.setattr(updater, "resolve_latest_version", lambda: "3.33.0")
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
    monkeypatch.setattr(updater, "resolve_latest_version", lambda: "3.35.3")
    monkeypatch.setattr(updater, "_run_installer", lambda v=None: True)
    monkeypatch.setattr(updater, "installed_version_on_path", lambda: "3.35.2")

    ok, msg = updater.upgrade_current_install()

    assert ok is False
    assert "3.35.2 is what installed" in msg


def test_frozen_upgrade_failure_hands_back_the_manual_command(monkeypatch):
    monkeypatch.setattr(updater, "_is_frozen", lambda: True)
    monkeypatch.setattr(updater, "get_current_version", lambda: "3.32.5")
    monkeypatch.setattr(updater, "get_latest_version", lambda: "3.33.0")
    monkeypatch.setattr(updater, "resolve_latest_version", lambda: "3.33.0")
    monkeypatch.setattr(updater, "_run_installer", lambda v=None: False)

    ok, msg = updater.upgrade_current_install()

    assert ok is False
    assert "install.sh" in msg


def test_frozen_upgrade_does_not_reinstall_when_current(monkeypatch):
    monkeypatch.setattr(updater, "_is_frozen", lambda: True)
    monkeypatch.setattr(updater, "get_current_version", lambda: "3.33.0")
    monkeypatch.setattr(updater, "get_latest_version", lambda: "3.33.0")
    monkeypatch.setattr(updater, "resolve_latest_version", lambda: "3.33.0")

    def boom(v=None):
        raise AssertionError("must not re-download when already latest")

    monkeypatch.setattr(updater, "_run_installer", boom)
    ok, msg = updater.upgrade_current_install()

    assert ok is True
    assert "is the latest" in msg


def test_frozen_upgrade_unreachable_channel_never_runs_the_installer(monkeypatch):
    monkeypatch.setattr(updater, "_is_frozen", lambda: True)
    monkeypatch.setattr(updater, "get_current_version", lambda: "3.33.0")
    monkeypatch.setattr(updater, "resolve_latest_version", lambda: None)

    def boom(v=None):
        raise AssertionError("never reinstall on a failed version check")

    monkeypatch.setattr(updater, "_run_installer", boom)
    ok, msg = updater.upgrade_current_install()

    assert ok is False
    assert "could not reach GitHub or PyPI" in msg


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
    monkeypatch.setattr(updater, "resolve_latest_version", lambda: "3.36.0")
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
    monkeypatch.setattr(updater, "resolve_latest_version", lambda: "3.36.0")
    monkeypatch.setattr(updater, "_run_installer", lambda v=None: True)
    monkeypatch.setattr(updater, "installed_version_on_path", lambda: "3.35.2")

    assert updater.auto_upgrade() is False


def test_frozen_auto_upgrade_skips_when_already_current(monkeypatch):
    monkeypatch.setattr(updater, "is_shadow_install", lambda: False)
    monkeypatch.setattr(updater, "_is_frozen", lambda: True)
    monkeypatch.setattr(updater, "get_current_version", lambda: "3.36.0")
    monkeypatch.setattr(updater, "get_latest_version", lambda: "3.36.0")
    monkeypatch.setattr(updater, "resolve_latest_version", lambda: "3.36.0")

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


def test_check_and_upgrade_treats_up_to_date_as_success(monkeypatch):
    monkeypatch.setattr(updater, "get_current_version", lambda: "3.36.0")
    monkeypatch.setattr(updater, "get_latest_version", lambda: "3.36.0")
    monkeypatch.setattr(updater, "resolve_latest_version", lambda: "3.36.0")
    monkeypatch.setattr(updater, "_cache_latest_version", lambda v: None)

    ok, msg = updater.check_and_upgrade()

    assert ok is True and "Already up to date" in msg


def test_background_binary_update_does_not_depend_on_pypi(monkeypatch):
    monkeypatch.setattr(updater, '_is_frozen', lambda: True)
    monkeypatch.setattr(updater, 'get_current_version', lambda: '3.41.0')
    monkeypatch.setattr(updater, 'latest_release_tag', lambda: '3.42.0')
    monkeypatch.setattr(updater, 'get_latest_version',
                        lambda: (_ for _ in ()).throw(AssertionError('PyPI queried')))
    cached = []
    monkeypatch.setattr(updater, '_cache_latest_version', cached.append)
    monkeypatch.setattr(updater, 'auto_upgrade', lambda: True)
    ok, message = updater.check_and_upgrade()
    assert ok and '3.42.0' in message
    assert cached == ['3.42.0']


def test_frozen_installs_ask_github_not_pypi(monkeypatch):
    # The binary is downloaded from GitHub Releases, so GitHub decides whether
    # it's current. PyPI's index lags every upload by a minute or two, which
    # made `cs upgrade` report the version it had just replaced — five times
    # in one afternoon.
    monkeypatch.setattr(updater, "_is_frozen", lambda: True)
    monkeypatch.setattr(updater, "latest_release_tag", lambda: "3.40.0")
    monkeypatch.setattr(updater, "get_latest_version",
                        lambda: (_ for _ in ()).throw(
                            AssertionError("must not ask PyPI first")))

    assert updater.resolve_latest_version() == "3.40.0"


def test_frozen_falls_back_to_pypi_when_github_is_unreachable(monkeypatch):
    monkeypatch.setattr(updater, "_is_frozen", lambda: True)
    monkeypatch.setattr(updater, "latest_release_tag", lambda: None)
    monkeypatch.setattr(updater, "get_latest_version", lambda: "3.39.0")

    assert updater.resolve_latest_version() == "3.39.0"


def test_pip_installs_still_ask_pypi(monkeypatch):
    monkeypatch.setattr(updater, "_is_frozen", lambda: False)
    monkeypatch.setattr(updater, "latest_release_tag",
                        lambda: (_ for _ in ()).throw(
                            AssertionError("GitHub is not the pip channel")))
    monkeypatch.setattr(updater, "get_latest_version", lambda: "3.40.0")

    assert updater.resolve_latest_version() == "3.40.0"


def test_release_tag_strips_the_v_prefix(monkeypatch):
    class _Resp:
        def read(self):
            return b'{"tag_name": "v3.40.0"}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(updater.urllib.request, "urlopen",
                        lambda req, timeout=None: _Resp())
    assert updater.latest_release_tag() == "3.40.0"


def _fake_venv(tmp_path):
    """A uv-tool-style venv: bin/python3 -> symlink to a base interpreter that
    lives somewhere else entirely (Homebrew Cellar, pyenv, uv-managed CPython)."""
    base = tmp_path / "Cellar" / "python@3.13" / "bin"
    base.mkdir(parents=True)
    (base / "python3.13").write_text("")
    venv_bin = tmp_path / "uv" / "tools" / "claude-statusbar" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "python3").symlink_to(base / "python3.13")
    (venv_bin / "cs").write_text("")
    return venv_bin


def test_shadow_install_not_triggered_by_symlinked_venv_interpreter(monkeypatch, tmp_path):
    # Regression: resolving sys.executable followed the venv's python3 symlink
    # out to the base interpreter, so entry.parent never matched and every
    # uv-tool install refused to auto-upgrade itself.
    venv_bin = _fake_venv(tmp_path)
    local_bin = tmp_path / ".local" / "bin"
    local_bin.mkdir(parents=True)
    (local_bin / "cs").symlink_to(venv_bin / "cs")   # uv's shared entry point
    monkeypatch.setattr(updater.shutil, "which", lambda name: str(local_bin / "cs"))
    monkeypatch.setattr(updater.sys, "executable", str(venv_bin / "python3"))

    assert updater.is_shadow_install() is False


def test_shadow_install_still_detects_foreign_entrypoint(monkeypatch, tmp_path):
    # The case the guard exists for: `cs` on PATH is a different install
    # (here a standalone binary), so this copy must not upgrade over it.
    venv_bin = _fake_venv(tmp_path)
    local_bin = tmp_path / ".local" / "bin"
    local_bin.mkdir(parents=True)
    (local_bin / "cs").write_text("")   # a real file, not a link into our venv
    monkeypatch.setattr(updater.shutil, "which", lambda name: str(local_bin / "cs"))
    monkeypatch.setattr(updater.sys, "executable", str(venv_bin / "python3"))

    assert updater.is_shadow_install() is True


# ---------------------------------------------------------------------------
# #66: GBK Windows — undecodable uv output and a half-installed tool env
# ---------------------------------------------------------------------------

def test_run_upgrade_survives_output_the_locale_cannot_decode(monkeypatch):
    # 0x82 is the byte from the issue's traceback: invalid GBK, and invalid
    # UTF-8 too. Whatever the locale codec, the child's bytes aren't decoded.
    cmd = [sys.executable, "-c",
           "import sys; sys.stdout.buffer.write(b'\\x82\\xff ok'); "
           "sys.stderr.buffer.write(b'\\xe2\\x9c\\x93')"]
    assert updater._run_upgrade(cmd) is True


def test_run_upgrade_forces_utf8_in_the_child(monkeypatch):
    captured = {}

    class FakeResult:
        returncode = 0

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        return FakeResult()

    monkeypatch.setattr(updater.subprocess, "run", fake_run)
    updater._run_upgrade(["uv", "tool", "install", "--upgrade", "x"])
    assert "text" not in captured and "encoding" not in captured
    assert captured["env"]["PYTHONUTF8"] == "1"


def _uv_upgrade_setup(monkeypatch, run_results, health):
    monkeypatch.setattr(updater, "_is_frozen", lambda: False)
    monkeypatch.setattr(updater, "is_shadow_install", lambda: False)
    monkeypatch.setattr(updater, "get_current_version", lambda: "3.43.3")
    cmd = ["uv", "tool", "install", "--upgrade", "claude-statusbar"]
    monkeypatch.setattr(updater, "get_upgrade_command", lambda: cmd)
    runs = []
    results = iter(run_results)
    monkeypatch.setattr(updater, "_run_upgrade",
                        lambda c: runs.append(c) or next(results))
    health_iter = iter(health)
    monkeypatch.setattr(updater, "_entrypoint_healthy",
                        lambda: next(health_iter))
    return runs


def test_failed_upgrade_that_broke_cs_is_retried(monkeypatch):
    runs = _uv_upgrade_setup(monkeypatch, [False, True], [False, True])
    ok, msg = updater.upgrade_current_install()
    assert ok is True
    assert len(runs) == 2


def test_failed_upgrade_that_stays_broken_says_so(monkeypatch):
    runs = _uv_upgrade_setup(monkeypatch, [False, False], [False, False])
    ok, msg = updater.upgrade_current_install()
    assert ok is False
    assert len(runs) == 2
    assert "broken" in msg
    assert "uv tool install --upgrade claude-statusbar" in msg


def test_failed_upgrade_with_healthy_cs_is_not_retried(monkeypatch):
    runs = _uv_upgrade_setup(monkeypatch, [False], [True])
    ok, msg = updater.upgrade_current_install()
    assert ok is False
    assert len(runs) == 1
    assert "broken" not in msg


def test_entrypoint_healthy_reads_exit_code_not_output(monkeypatch, tmp_path):
    # A broken uv entry prints a ModuleNotFoundError traceback; its last word
    # must not pass for a version.
    fake = tmp_path / "cs"
    fake.write_text(f"#!{sys.executable}\n"
                    "import sys\n"
                    "sys.stderr.write(\"ModuleNotFoundError: No module named "
                    "'claude_statusbar'\\n\")\n"
                    "sys.exit(1)\n")
    fake.chmod(0o755)
    monkeypatch.setattr(updater, "path_entrypoint", lambda: fake)
    assert updater._entrypoint_healthy() is False


# Windows can't delete or overwrite a file a process holds, and cs.exe always
# is (daemon + every render). `uv tool install --upgrade` then half-deletes the
# env; `uv tool upgrade` with the launchers renamed aside works. Both measured
# on Windows 11.

def test_windows_uv_uses_in_place_tool_upgrade(monkeypatch):
    monkeypatch.setattr(updater, "_is_frozen", lambda: False)
    monkeypatch.setattr(updater, "detect_install_channel", lambda exe=None: "uv")
    monkeypatch.setattr(updater, "_find_tool", lambda name: "C:/uv/uv.exe")
    monkeypatch.setattr(updater.sys, "platform", "win32")
    assert updater.get_upgrade_command() == [
        "C:/uv/uv.exe", "tool", "upgrade", "claude-statusbar"]


@pytest.fixture
def winbin(tmp_path, monkeypatch):
    monkeypatch.setattr(updater.sys, "platform", "win32")
    for name in updater._ENTRY_EXES:
        (tmp_path / name).write_text("old")
    monkeypatch.setattr(updater, "path_entrypoint", lambda: tmp_path / "cs.exe")
    return tmp_path


UV_UPGRADE = ["uv", "tool", "upgrade", "claude-statusbar"]


def test_windows_uv_upgrade_moves_launchers_aside(winbin, monkeypatch):
    def fake_uv(cmd, **k):
        # uv must find the in-use launchers gone, then writes new ones
        assert not (winbin / "cs.exe").exists()
        for name in updater._ENTRY_EXES:
            (winbin / name).write_text("new")
        return True

    monkeypatch.setattr(updater, "_run_upgrade_command", fake_uv)
    assert updater._run_upgrade(UV_UPGRADE) is True
    assert (winbin / "cs.exe").read_text() == "new"
    # the old launchers weren't running here, so they're cleaned up at once
    assert list(winbin.glob("*.old-*")) == []


@pytest.mark.parametrize("uv_ok", [True, False])
def test_windows_uv_upgrade_restores_launchers_uv_did_not_write(
        winbin, monkeypatch, uv_ok):
    # False: uv failed. True: "Nothing to upgrade" (already latest / pinned)
    # exits 0 without writing launchers. Either way cs.exe must come back.
    monkeypatch.setattr(updater, "_run_upgrade_command", lambda cmd, **k: uv_ok)
    assert updater._run_upgrade(UV_UPGRADE) is uv_ok
    for name in updater._ENTRY_EXES:
        assert (winbin / name).read_text() == "old"
    assert list(winbin.glob("*.old-*")) == []


def test_windows_uv_upgrade_clears_stale_launchers(winbin, monkeypatch):
    (winbin / "cs.exe.old-1").write_text("stale")
    monkeypatch.setattr(updater, "_run_upgrade_command", lambda cmd, **k: True)
    updater._run_upgrade(UV_UPGRADE)
    assert not (winbin / "cs.exe.old-1").exists()


def test_non_windows_upgrade_touches_no_launchers(winbin, monkeypatch):
    monkeypatch.setattr(updater.sys, "platform", "linux")
    monkeypatch.setattr(updater, "_run_upgrade_command", lambda cmd, **k: True)
    updater._run_upgrade(UV_UPGRADE)
    assert list(winbin.glob("*.old-*")) == []


def test_windows_pip_cs_upgrade_prints_steps_instead_of_running(monkeypatch):
    runs = _uv_upgrade_setup(monkeypatch, [], [])
    monkeypatch.setattr(updater, "get_upgrade_command", lambda: [
        "python", "-m", "pip", "install", "--upgrade", "claude-statusbar"])
    monkeypatch.setattr(updater.sys, "platform", "win32")
    ok, msg = updater.upgrade_current_install()
    assert ok is False
    assert runs == []
    assert "cs daemon stop" in msg


def test_windows_pip_auto_upgrade_never_runs(monkeypatch):
    monkeypatch.setattr(updater, "_is_frozen", lambda: False)
    monkeypatch.setattr(updater, "is_shadow_install", lambda: False)
    monkeypatch.setattr(updater, "get_upgrade_command", lambda: [
        "python", "-m", "pip", "install", "--upgrade", "claude-statusbar"])
    monkeypatch.setattr(updater.sys, "platform", "win32")

    def boom(*a, **k):
        raise AssertionError("must not upgrade pip in place on Windows")

    monkeypatch.setattr(updater, "_run_upgrade", boom)
    assert updater.auto_upgrade() is False


def test_windows_uv_upgrade_judged_by_installed_version(winbin, monkeypatch):
    # uv upgraded the env, then lost the launcher copy to a render (os error
    # 32) and exited 1. The package is new; the restored launcher runs it.
    versions = iter(["3.43.6", "3.43.7"])
    monkeypatch.setattr(updater, "get_current_version", lambda: next(versions))
    monkeypatch.setattr(updater, "_run_upgrade_command", lambda cmd, **k: False)
    assert updater._run_upgrade(UV_UPGRADE) is True
    assert (winbin / "cs.exe").read_text() == "old"


def test_windows_uv_upgrade_failure_with_same_version_fails(winbin, monkeypatch):
    monkeypatch.setattr(updater, "get_current_version", lambda: "3.43.6")
    monkeypatch.setattr(updater, "_run_upgrade_command", lambda cmd, **k: False)
    assert updater._run_upgrade(UV_UPGRADE) is False


def _uv_env_with_copied_launcher(tmp_path, monkeypatch, receipt_path):
    env = tmp_path / "uv" / "tools" / "claude-statusbar"
    (env / "Scripts").mkdir(parents=True)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    entry = bindir / "cs.exe"
    entry.write_text("launcher copy")
    (env / "uv-receipt.toml").write_text(
        "[tool]\nentrypoints = [\n"
        f'    {{ name = "cs", install-path = "{receipt_path(entry)}", '
        'from = "claude-statusbar" },\n]\n')
    monkeypatch.setattr(updater.sys, "executable", str(env / "Scripts" / "python.exe"))
    monkeypatch.setattr(updater.sys, "prefix", str(env))
    monkeypatch.setattr(updater, "path_entrypoint", lambda: entry.resolve())


def test_copied_uv_launcher_is_not_a_shadow(tmp_path, monkeypatch):
    # Windows uv copies cs.exe into its bin dir; the receipt records it.
    _uv_env_with_copied_launcher(tmp_path, monkeypatch, lambda e: e.as_posix())
    assert updater.is_shadow_install() is False


def test_launcher_missing_from_receipt_is_still_a_shadow(tmp_path, monkeypatch):
    _uv_env_with_copied_launcher(
        tmp_path, monkeypatch, lambda e: (e.parent / "other.exe").as_posix())
    assert updater.is_shadow_install() is True
