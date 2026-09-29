"""The uv upgrade commands we build must parse with the real uv (#67).

3.43.8 shipped `uv tool upgrade --refresh-package`, which uv rejects
("unexpected argument"), so every Windows `cs upgrade` failed. A grep of
`--help` had "confirmed" the flag: it only appears there inside
--reinstall-package's description. Run the real binary instead. uv checks
arguments before doing anything, so against an empty tool dir and offline a
valid command fails later ("not installed", no network) and a bad flag fails
at parse time with "unexpected argument".
"""
import shutil
import subprocess

import pytest

from claude_statusbar import updater

UV = shutil.which("uv")
pytestmark = pytest.mark.skipif(UV is None, reason="uv not installed")


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
def test_upgrade_command_parses_with_real_uv(platform, tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "_is_frozen", lambda: False)
    monkeypatch.setattr(updater, "detect_install_channel", lambda exe=None: "uv")
    monkeypatch.setattr(updater, "_find_tool", lambda name: UV)
    monkeypatch.setattr(updater.sys, "platform", platform)
    cmd = updater.get_upgrade_command()
    assert cmd[0] == UV

    env = {
        "PATH": "",
        "UV_TOOL_DIR": str(tmp_path / "tools"),
        "UV_TOOL_BIN_DIR": str(tmp_path / "bin"),
        "UV_CACHE_DIR": str(tmp_path / "cache"),
        "UV_PYTHON_INSTALL_DIR": str(tmp_path / "py"),
        "UV_OFFLINE": "1",
        "HOME": str(tmp_path),
    }
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=60,
                         env=env, encoding="utf-8", errors="replace")
    assert "unexpected argument" not in out.stderr, out.stderr
    assert "Usage:" not in out.stderr, out.stderr
