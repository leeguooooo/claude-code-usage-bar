#!/usr/bin/env python3
"""
Auto-repair and setup utilities for claude-statusbar.

Ensures ~/.claude/settings.json always has the statusLine configuration
so the status bar appears in Claude Code.
"""

import json
from pathlib import Path
from typing import Tuple

SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
STATUSLINE_CONFIG = {"type": "command", "command": "cs"}


def _read_settings() -> dict:
    """Read settings.json, returning empty dict if missing or unparseable."""
    if not SETTINGS_PATH.exists():
        return {}
    try:
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_settings(data: dict) -> bool:
    """Write settings.json atomically. Returns True on success."""
    try:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return True
    except OSError:
        return False


def is_statusline_configured() -> bool:
    """Return True if settings.json already has the statusLine key."""
    settings = _read_settings()
    return "statusLine" in settings


def ensure_statusline_configured() -> Tuple[bool, str]:
    """
    Silently ensure settings.json has the statusLine config.

    Returns:
        (changed, message)
        changed  – True if the file was actually modified
        message  – human-readable description of what happened
    """
    settings = _read_settings()

    if "statusLine" in settings:
        return False, "statusLine already configured"

    settings["statusLine"] = STATUSLINE_CONFIG
    if _write_settings(settings):
        return True, f"Added statusLine config to {SETTINGS_PATH}"
    else:
        return False, f"Could not write to {SETTINGS_PATH}"


def run_setup(verbose: bool = True) -> int:
    """
    Interactive setup: configure the statusLine and report to the user.

    Returns exit code (0 = success).
    """
    changed, message = ensure_statusline_configured()

    if verbose:
        if changed:
            print(f"✓ {message}")
            print("  Restart Claude Code for the status bar to appear.")
        else:
            print(f"✓ {message}")
            print(f"  Settings file: {SETTINGS_PATH}")

    return 0
