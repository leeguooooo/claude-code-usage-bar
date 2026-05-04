"""Phase C: launchd / systemd service installer.

These tests focus on the file-content + path semantics of the installer.
The actual `launchctl bootstrap` / `systemctl --user enable` calls aren't
exercised — those need real OS state. Manual verification covers them.
"""

import os
import sys
from pathlib import Path

import pytest

from claude_statusbar import service


def test_platform_detection():
    plat = service._platform()
    assert plat in {"macos", "linux", "unsupported"}
    if sys.platform == "darwin":
        assert plat == "macos"
    elif sys.platform.startswith("linux"):
        assert plat == "linux"


def test_launchd_plist_structure():
    body = service._build_launchd_plist("/usr/local/bin/cs")
    assert "<?xml" in body
    assert "<key>Label</key>" in body
    assert f"<string>{service.LAUNCHD_LABEL}</string>" in body
    # Critical: must invoke our daemon _run subcommand, not anything else.
    assert "<string>/usr/local/bin/cs</string>" in body
    assert "<string>daemon</string>" in body
    assert "<string>_run</string>" in body
    # KeepAlive bounces a crashed daemon — the whole point of Phase C.
    assert "<key>KeepAlive</key>" in body
    assert "<true/>" in body
    assert "<key>RunAtLoad</key>" in body
    # ThrottleInterval keeps a crash-loop from melting the CPU.
    assert "<key>ThrottleInterval</key>" in body


def test_systemd_unit_structure():
    body = service._build_systemd_unit("/usr/local/bin/cs")
    assert "[Unit]" in body
    assert "[Service]" in body
    assert "[Install]" in body
    assert "ExecStart=/usr/local/bin/cs daemon _run" in body
    # Must auto-restart on crash.
    assert "Restart=always" in body
    # WantedBy=default.target so it runs at user-login under systemd.
    assert "WantedBy=default.target" in body


def test_launchd_plist_path_uses_LaunchAgents():
    p = service.launchd_plist_path()
    assert p.parent == Path.home() / "Library" / "LaunchAgents"
    assert p.name == f"{service.LAUNCHD_LABEL}.plist"


def test_systemd_user_dir_respects_xdg(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert service.systemd_user_dir() == tmp_path / "systemd" / "user"


def test_systemd_user_dir_default_when_xdg_unset(monkeypatch):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    assert service.systemd_user_dir() == Path.home() / ".config" / "systemd" / "user"


def test_install_unsupported_platform(monkeypatch):
    monkeypatch.setattr(service, "_platform", lambda: "unsupported")
    ok, msg = service.install()
    assert ok is False
    assert "not supported" in msg.lower()


def test_plist_body_parses_as_valid_xml():
    """A nice-to-have but cheap insurance: plist text must be parseable XML.

    Unescaped path characters (& < >) in $HOME would silently produce
    malformed XML that launchctl rejects. The xml.sax.saxutils.escape
    fix means even paths with `&` survive.
    """
    import xml.etree.ElementTree as ET
    body = service._build_launchd_plist("/path/with/&-and-<-and->")
    # Must not raise.
    root = ET.fromstring(body)
    assert root.tag == "plist"


def test_systemd_exec_start_quotes_paths_with_spaces():
    """A path with spaces must be shell-quoted in ExecStart."""
    body = service._build_systemd_unit("/path with spaces/cs")
    # shlex.quote wraps in single quotes; verify the path survived intact.
    assert "ExecStart='/path with spaces/cs' daemon _run" in body


def test_uninstall_idempotent_when_nothing_installed(monkeypatch, tmp_path: Path):
    """Calling uninstall when no plist/unit exists should report success."""
    if service._platform() == "macos":
        monkeypatch.setattr(service, "launchd_plist_path", lambda: tmp_path / "nope.plist")
        ok, msg = service._macos_uninstall()
    elif service._platform() == "linux":
        monkeypatch.setattr(service, "systemd_unit_path", lambda: tmp_path / "nope.service")
        ok, msg = service._linux_uninstall()
    else:
        pytest.skip(f"unsupported platform {sys.platform!r}")
    assert ok is True
    assert "nothing to remove" in msg.lower()
