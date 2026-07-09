#!/usr/bin/env python3
"""
Auto-updater for claude-statusbar
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional, Tuple

import importlib.metadata as metadata

# Distribution name on PyPI (used for local version lookup)
DIST_NAME = "claude-statusbar"
PYPI_URL = "https://pypi.org/pypi/claude-statusbar/json"
# The background check writes the latest PyPI version here; the render path
# reads it (cheap, no network) to show a `↑<newver>` update hint on the bar.
LATEST_VERSION_CACHE = Path.home() / ".cache" / "claude-statusbar" / "latest_version.json"


def _cache_latest_version(version: str) -> None:
    """Persist the latest-known PyPI version for the render path to read."""
    try:
        import time
        from .cache import atomic_write_text
        LATEST_VERSION_CACHE.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            LATEST_VERSION_CACHE,
            json.dumps({"version": str(version), "checked_at": time.time()}),
        )
    except Exception:
        pass


def get_current_version() -> str:
    """Best-effort local installed version."""
    try:
        return metadata.version(DIST_NAME)
    except metadata.PackageNotFoundError:
        # Running from source without an installed distribution.
        return "0.0.0"


def get_latest_version() -> Optional[str]:
    """Get latest version from PyPI"""
    try:
        with urllib.request.urlopen(PYPI_URL, timeout=5) as response:
            data = json.loads(response.read().decode())
            latest = data["info"]["version"]
            _cache_latest_version(latest)
            return latest
    except (urllib.error.URLError, json.JSONDecodeError, KeyError):
        return None


def compare_versions(current: str, latest: str) -> bool:
    """Compare versions (True if latest > current)"""
    try:

        def to_int_parts(v: str) -> list[int]:
            parts: list[int] = []
            for chunk in v.split("."):
                digits = ""
                for ch in chunk:
                    if ch.isdigit():
                        digits += ch
                    else:
                        break
                parts.append(int(digits or 0))
            return parts

        current_parts = to_int_parts(current)
        latest_parts = to_int_parts(latest)

        # Pad shorter version with zeros
        max_len = max(len(current_parts), len(latest_parts))
        current_parts.extend([0] * (max_len - len(current_parts)))
        latest_parts.extend([0] * (max_len - len(latest_parts)))

        return latest_parts > current_parts
    except (ValueError, AttributeError):
        return False


def detect_install_channel(
    executable: str | Path | None = None,
) -> str:
    """Infer how claude-statusbar is currently installed."""
    raw = Path(executable or sys.executable).expanduser()
    candidates = [raw]
    if executable is None:
        candidates.append(Path(sys.prefix).expanduser())
    try:
        candidates.append(raw.resolve())
    except OSError:
        pass

    for path in candidates:
        parts = path.parts
        if "uv" in parts and "tools" in parts and DIST_NAME in parts:
            return "uv"

        if "pipx" in parts and "venvs" in parts and DIST_NAME in parts:
            return "pipx"

    return "pip"


def get_upgrade_command(
    executable: str | Path | None = None,
) -> list[str]:
    """Return the most appropriate self-upgrade command for this install."""
    channel = detect_install_channel(executable)

    if channel == "uv" and shutil.which("uv"):
        return ["uv", "tool", "install", "--upgrade", DIST_NAME]

    if channel == "pipx" and shutil.which("pipx"):
        return ["pipx", "upgrade", DIST_NAME]

    return [sys.executable, "-m", "pip", "install", "--upgrade", DIST_NAME]


# Hard cap so a hung pip/uv install can NEVER freeze a Claude Code statusLine
# render. 60s is generous for fast networks and short-circuits cleanly on slow
# ones — the user gets a normal status line at the next session.
_UPGRADE_TIMEOUT_S = 60


def _run_upgrade(cmd) -> bool:
    """Run an upgrade command with a timeout. Returns True on success."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_UPGRADE_TIMEOUT_S,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        logging.error(f"Upgrade command {cmd!r} failed: {e}")
        return False


def auto_upgrade() -> bool:
    """Attempt automatic upgrade. Bounded by _UPGRADE_TIMEOUT_S per attempt."""
    if _run_upgrade(get_upgrade_command()):
        return True

    if shutil.which("pipx"):
        if _run_upgrade(["pipx", "upgrade", DIST_NAME]):
            return True

    return _run_upgrade(
        [sys.executable, "-m", "pip", "install", "--upgrade", DIST_NAME]
    )


def upgrade_current_install() -> Tuple[bool, str]:
    """Upgrade the environment that is actually running this CLI."""
    current = get_current_version()
    cmd = get_upgrade_command()

    if _run_upgrade(cmd):
        refreshed = get_current_version()
        return True, f"Upgraded {DIST_NAME} from v{current} to v{refreshed}"

    rendered_cmd = " ".join(cmd)
    return False, f"Upgrade failed. Run manually: {rendered_cmd}"


def spawn_background_upgrade_check() -> None:
    """Fire-and-forget: run the version check + upgrade in a DETACHED
    subprocess (`python -m claude_statusbar.updater`) so it never blocks a
    status-line render — the upgrade itself can take tens of seconds. The
    detached process re-checks the 24h marker is irrelevant here (the caller
    already gated on it); it just performs the check_and_upgrade once.

    Best-effort: any spawn failure is swallowed so a render is never harmed.
    On a successful upgrade the on-disk package mtime changes, and the daemon's
    code-drift detection (render_thin._is_fresh) restarts it onto new code.
    """
    try:
        subprocess.Popen(
            [sys.executable, "-m", "claude_statusbar.updater"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )
    except (OSError, ValueError):
        pass


def check_and_upgrade() -> Tuple[bool, str]:
    """Check for updates and upgrade if available"""
    latest = get_latest_version()
    current = get_current_version()

    if not latest:
        return False, "Unable to check for updates"

    if not compare_versions(current, latest):
        return False, f"Already up to date (v{current})"

    # New version available, try to upgrade
    if auto_upgrade():
        return True, f"Upgraded from v{current} to v{latest}"
    else:
        return (
            False,
            f"Update available (v{latest}) but auto-upgrade failed. Run: pip install --upgrade claude-statusbar",
        )


if __name__ == "__main__":
    success, message = check_and_upgrade()
    print(message)
    sys.exit(0 if success else 1)
