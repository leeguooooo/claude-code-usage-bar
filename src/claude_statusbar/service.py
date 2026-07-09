"""OS-level service installer for the cs daemon (Phase C).

Lazy-spawn (Phase B) is the default: the daemon comes up the first time
``cs render`` notices stale output, and stays up as long as you don't
``cs daemon stop`` it. That covers 99% of cases.

This module is for users who want stronger guarantees: daemon auto-starts
on login, gets restarted by the OS if it crashes, and survives reboots
without any human action. macOS uses launchd; Linux uses systemd user
units; Windows is unsupported (no need yet — Claude Code's primary users
are macOS/Linux).

Public API: ``install()``, ``uninstall()``, ``status()``. Each returns
``(ok: bool, message: str)``. The ``cs daemon install`` /
``cs daemon uninstall`` subcommands route here.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Tuple
from xml.sax.saxutils import escape as _xml_escape

from .cache import atomic_write_text


LAUNCHD_LABEL = "com.claude-statusbar.daemon"
SYSTEMD_UNIT = "claude-statusbar-daemon.service"
_SUBPROCESS_TIMEOUT = 10.0  # launchctl/systemctl should never take longer


# ---------------------------------------------------------------------------
# Platform detection + paths
# ---------------------------------------------------------------------------
def _platform() -> str:
    """Return 'macos', 'linux', or 'unsupported'."""
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    return "unsupported"


def launchagents_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def launchd_plist_path() -> Path:
    return launchagents_dir() / f"{LAUNCHD_LABEL}.plist"


def systemd_user_dir() -> Path:
    """XDG-respecting systemd user unit dir."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "systemd" / "user"


def systemd_unit_path() -> Path:
    return systemd_user_dir() / SYSTEMD_UNIT


# ---------------------------------------------------------------------------
# Resolve `cs` binary (mirror setup.py's logic so the unit file is self-contained)
# ---------------------------------------------------------------------------
def _resolve_cs() -> str:
    """Best-effort absolute path to the `cs` binary, for the unit file.

    Delegates to setup._resolve_cs_command() so the lookup logic doesn't
    drift between settings.json writers and OS service installers.
    """
    from .setup import _resolve_cs_command
    return _resolve_cs_command()


# ---------------------------------------------------------------------------
# macOS launchd
# ---------------------------------------------------------------------------
def _build_launchd_plist(cs_path: str) -> str:
    """plist body for launchd. KeepAlive bounces a *crashed* daemon
    automatically, RunAtLoad covers cold boots.

    `KeepAlive` is `{SuccessfulExit: false}`, not plain `true`. Plain `true`
    restarts the job whatever its exit status, so whenever the thin client's
    lazy-spawn already owned the pidfile, launchd's own instance exited
    "daemon already running", was restarted `ThrottleInterval` seconds later,
    and looped forever — 47429 such lines had piled up in one user's
    daemon.stderr.log. A clean exit now means "a daemon is running, nothing to
    do" and launchd leaves it alone; a crash still bounces.

    All path fields are XML-escaped — a $HOME containing `&`, `<`, or `>`
    (rare but possible) would otherwise produce malformed plist XML that
    launchctl rejects.
    """
    cs_esc = _xml_escape(cs_path)
    home_esc = _xml_escape(str(Path.home()))
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LAUNCHD_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{cs_esc}</string>
        <string>daemon</string>
        <string>_run</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>ThrottleInterval</key>
    <integer>10</integer>
    <key>StandardOutPath</key>
    <string>{home_esc}/.cache/claude-statusbar/daemon.stdout.log</string>
    <key>StandardErrorPath</key>
    <string>{home_esc}/.cache/claude-statusbar/daemon.stderr.log</string>
</dict>
</plist>
"""


def _launchctl(*args: str) -> Tuple[int, str, str]:
    """Run `launchctl <args>` with a hard timeout — never hang `cs daemon
    install` if launchd is wedged."""
    try:
        p = subprocess.run(
            ["launchctl", *args],
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return 124, "", f"launchctl {' '.join(args)} timed out after {_SUBPROCESS_TIMEOUT}s"
    return p.returncode, p.stdout, p.stderr


def _macos_install() -> Tuple[bool, str]:
    plist_path = launchd_plist_path()
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    body = _build_launchd_plist(_resolve_cs())
    if not atomic_write_text(plist_path, body):
        return False, f"Could not write {plist_path}"
    # `launchctl bootstrap gui/$UID` is the modern way to load a user agent.
    uid = os.getuid()
    rc, _, err = _launchctl("bootstrap", f"gui/{uid}", str(plist_path))
    # Already-loaded → idempotent success.
    if rc != 0 and "already" not in err.lower() and "service already loaded" not in err.lower():
        # Older macOS: fall back to `launchctl load`.
        rc2, _, err2 = _launchctl("load", str(plist_path))
        if rc2 != 0:
            return False, (
                f"plist written to {plist_path}, but `launchctl bootstrap` "
                f"failed: {err.strip() or err2.strip()}. Reboot or run "
                f"`launchctl load -w {plist_path}` manually."
            )
    return True, (
        f"LaunchAgent installed at {plist_path}. The daemon will auto-start on "
        f"login and be re-spawned by launchd if it crashes."
    )


def _macos_uninstall() -> Tuple[bool, str]:
    plist_path = launchd_plist_path()
    if not plist_path.exists():
        return True, f"No LaunchAgent at {plist_path}; nothing to remove."
    uid = os.getuid()
    # Best-effort unload; we delete the file even if launchctl complains.
    _launchctl("bootout", f"gui/{uid}/{LAUNCHD_LABEL}")
    try:
        plist_path.unlink()
    except OSError as e:
        return False, f"Could not delete {plist_path}: {e}"
    return True, f"LaunchAgent removed ({plist_path}). Daemon may still be running — `cs daemon stop` to kill it now."


def _macos_status() -> Tuple[bool, str]:
    plist_path = launchd_plist_path()
    if not plist_path.exists():
        return False, f"not installed (no {plist_path})"
    rc, out, _ = _launchctl("print", f"gui/{os.getuid()}/{LAUNCHD_LABEL}")
    if rc != 0:
        return False, f"plist exists at {plist_path} but launchd doesn't know it (try `cs daemon install` again)"
    # Find the "state = running"-ish line.
    state = "unknown"
    for line in out.splitlines():
        ls = line.strip()
        if ls.startswith("state ="):
            state = ls.split("=", 1)[1].strip()
            break
    return True, f"installed ({plist_path}), launchd state: {state}"


# ---------------------------------------------------------------------------
# Linux systemd user unit
# ---------------------------------------------------------------------------
def _build_systemd_unit(cs_path: str) -> str:
    """systemd user unit. ExecStart is shell-quoted so paths with spaces
    or unit-special characters survive systemd's parser.

    `Restart=on-failure`, not `always`: same reasoning as launchd's
    `KeepAlive={SuccessfulExit: false}`. When a lazy-spawned daemon already
    holds the pidfile, systemd's own instance exits 0 ("a daemon is running,
    nothing to do") and must be left alone — `always` re-ran it every
    RestartSec forever, and also undid `cs daemon stop` (clean exit,
    immediately relaunched). A crash still restarts.
    """
    cs_quoted = shlex.quote(cs_path)
    return f"""[Unit]
Description=claude-statusbar render daemon
After=network.target

[Service]
Type=simple
ExecStart={cs_quoted} daemon _run
Restart=on-failure
RestartSec=5
StandardOutput=append:%h/.cache/claude-statusbar/daemon.stdout.log
StandardError=append:%h/.cache/claude-statusbar/daemon.stderr.log

[Install]
WantedBy=default.target
"""


def _systemctl_user(*args: str) -> Tuple[int, str, str]:
    """Run `systemctl --user <args>` with a hard timeout."""
    try:
        p = subprocess.run(
            ["systemctl", "--user", *args],
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return 124, "", f"systemctl --user {' '.join(args)} timed out after {_SUBPROCESS_TIMEOUT}s"
    return p.returncode, p.stdout, p.stderr


def _linux_install() -> Tuple[bool, str]:
    if shutil.which("systemctl") is None:
        return False, (
            "systemctl not found. systemd is required for service mode on "
            "Linux. Use `cs daemon start` for the lazy-spawn model instead."
        )
    unit_path = systemd_unit_path()
    unit_path.parent.mkdir(parents=True, exist_ok=True)
    body = _build_systemd_unit(_resolve_cs())
    if not atomic_write_text(unit_path, body):
        return False, f"Could not write {unit_path}"
    rc1, _, e1 = _systemctl_user("daemon-reload")
    rc2, _, e2 = _systemctl_user("enable", "--now", SYSTEMD_UNIT)
    if rc2 != 0:
        return False, (
            f"unit written to {unit_path}, but `systemctl --user enable --now` "
            f"failed: {e1.strip() or e2.strip()}. Run it manually to debug."
        )
    return True, (
        f"systemd user unit installed at {unit_path} and started. The daemon "
        f"will auto-start on login. (You may need `loginctl enable-linger` for "
        f"it to survive logout — see systemd.unit(5).)"
    )


def _linux_uninstall() -> Tuple[bool, str]:
    unit_path = systemd_unit_path()
    if not unit_path.exists():
        return True, f"No systemd unit at {unit_path}; nothing to remove."
    if shutil.which("systemctl"):
        _systemctl_user("disable", "--now", SYSTEMD_UNIT)
        _systemctl_user("daemon-reload")
    try:
        unit_path.unlink()
    except OSError as e:
        return False, f"Could not delete {unit_path}: {e}"
    return True, f"systemd unit removed ({unit_path})."


def _linux_status() -> Tuple[bool, str]:
    unit_path = systemd_unit_path()
    if not unit_path.exists():
        return False, f"not installed (no {unit_path})"
    if shutil.which("systemctl") is None:
        return True, f"unit at {unit_path}, but systemctl not on PATH"
    rc, out, _ = _systemctl_user("is-active", SYSTEMD_UNIT)
    state = out.strip() or "unknown"
    return rc == 0, f"installed ({unit_path}), systemd state: {state}"


# ---------------------------------------------------------------------------
# Public entry points (called from cli._run_daemon_subcommand)
# ---------------------------------------------------------------------------
def install() -> Tuple[bool, str]:
    plat = _platform()
    if plat == "macos":
        return _macos_install()
    if plat == "linux":
        return _linux_install()
    return False, (
        f"OS-level service mode not supported on {sys.platform!r}. "
        "Use `cs daemon start` for the lazy-spawn model."
    )


def uninstall() -> Tuple[bool, str]:
    plat = _platform()
    if plat == "macos":
        return _macos_uninstall()
    if plat == "linux":
        return _linux_uninstall()
    return False, f"nothing to uninstall on {sys.platform!r}"


def status() -> Tuple[bool, str]:
    plat = _platform()
    if plat == "macos":
        return _macos_status()
    if plat == "linux":
        return _linux_status()
    return False, f"unsupported platform {sys.platform!r}"
