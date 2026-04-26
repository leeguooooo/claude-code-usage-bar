#!/usr/bin/env python3
"""
Auto-repair and setup utilities for claude-statusbar.

Ensures ~/.claude/settings.json always has the statusLine configuration
so the status bar appears in Claude Code.
"""

import json
import shutil
from pathlib import Path
from typing import Tuple

SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
STATUSLINE_CONFIG = {"type": "command", "command": "cs"}

# User-level slash command directory + the command files we ship.
COMMANDS_DIR = Path.home() / ".claude" / "commands"
COMMAND_FILES = (
    "statusbar.md",
    "statusbar-preview.md",
    "statusbar-style.md",
    "statusbar-theme.md",
    "statusbar-reset.md",
)


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


def _packaged_commands_dir() -> Path:
    """Return the directory bundled with the package that holds slash commands."""
    here = Path(__file__).resolve()
    return here.parent / "commands"


def install_commands(force: bool = False) -> Tuple[int, list[str]]:
    """Copy bundled slash commands into ~/.claude/commands/.

    Returns (count_installed, list_of_skipped_paths).
    """
    src_dir = _packaged_commands_dir()
    if not src_dir.is_dir():
        return 0, []

    COMMANDS_DIR.mkdir(parents=True, exist_ok=True)
    installed = 0
    skipped: list[str] = []

    for name in COMMAND_FILES:
        src = src_dir / name
        if not src.is_file():
            continue
        dst = COMMANDS_DIR / name
        if dst.exists() and not force:
            # Compare contents — if they match, count as installed; otherwise skip.
            try:
                if dst.read_text(encoding="utf-8") == src.read_text(encoding="utf-8"):
                    installed += 1
                    continue
            except OSError:
                pass
            skipped.append(str(dst))
            continue
        try:
            shutil.copy2(src, dst)
            installed += 1
        except OSError as e:
            skipped.append(f"{dst}: {e}")
    return installed, skipped


def run_setup(verbose: bool = True, install_cmds: bool = True) -> int:
    """
    Interactive setup: configure the statusLine, optionally install slash commands.

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

    if install_cmds:
        n, skipped = install_commands()
        if verbose:
            if n:
                print(f"✓ Installed {n} slash command(s) to {COMMANDS_DIR}")
            if skipped:
                print(f"  Skipped (already exist with different content; use --force to overwrite):")
                for s in skipped:
                    print(f"    {s}")
            print("  Try /statusbar in Claude Code.")

    return 0
