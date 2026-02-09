#!/usr/bin/env python3
"""
Auto-updater for claude-statusbar
"""

import json
import logging
import subprocess
import sys
import urllib.error
import urllib.request
from typing import Optional, Tuple

import importlib.metadata as metadata

# Distribution name on PyPI (used for local version lookup)
DIST_NAME = "claude-statusbar"
PYPI_URL = "https://pypi.org/pypi/claude-statusbar/json"


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
            return data["info"]["version"]
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


def auto_upgrade() -> bool:
    """Attempt automatic upgrade"""
    try:
        # Try pip upgrade
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "claude-statusbar"],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            return True

        # Try pipx upgrade if pip fails
        try:
            result = subprocess.run(
                ["pipx", "upgrade", "claude-statusbar"], capture_output=True, text=True
            )
            return result.returncode == 0
        except FileNotFoundError:
            pass

    except Exception as e:
        logging.error(f"Upgrade failed: {e}")

    return False


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
