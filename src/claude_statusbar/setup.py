#!/usr/bin/env python3
"""Auto-repair and setup utilities for claude-statusbar.

Ensures ~/.claude/settings.json always has a working statusLine pointing at
the `cs` CLI, and copies bundled slash commands into ~/.claude/commands/.

First-install reliability is the priority here: write atomically, prefer the
absolute path of `cs` when we can find it (so it survives PATH gaps that
GUI-launched Claude Code sees), and refresh stale configs from prior
installs.
"""

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Tuple

from .cache import atomic_write_text

SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
COMMANDS_DIR  = Path.home() / ".claude" / "commands"

# CLI binary names we ship — `cs` is shortest and the documented one.
OUR_COMMAND_NAMES = ("cs", "cstatus", "claude-statusbar")


def _resolve_cs_command() -> str:
    """Best-effort absolute path to our `cs` binary.

    Falls back to the bare name `cs` so `command not found` is at least
    visible to the user when they restart Claude Code.

    Resolution order:
      1. shutil.which("cs") — honors current PATH
      2. The script that's running us (sys.argv[0]) if it ends with cs/cstatus/...
      3. Common install locations probed in order
      4. Bare "cs"
    """
    cmd = shutil.which("cs") or shutil.which("cstatus") or shutil.which("claude-statusbar")
    if cmd and Path(cmd).is_file():
        return cmd

    # If we're being invoked as `python -m claude_statusbar`, sys.argv[0] is the script
    argv0 = Path(sys.argv[0]) if sys.argv and sys.argv[0] else None
    if argv0 and argv0.is_file() and argv0.name in OUR_COMMAND_NAMES:
        return str(argv0.resolve())

    for p in (
        Path.home() / ".local" / "bin" / "cs",
        Path.home() / ".local" / "share" / "uv" / "tools" / "claude-statusbar" / "bin" / "cs",
        Path.home() / ".local" / "pipx" / "venvs" / "claude-statusbar" / "bin" / "cs",
        Path("/usr/local/bin/cs"),
        Path("/opt/homebrew/bin/cs"),
    ):
        if p.is_file():
            return str(p)

    return "cs"


def _statusline_config() -> dict:
    """Build the statusLine entry we want to write."""
    return {"type": "command", "command": _resolve_cs_command()}


def _is_our_statusline(entry: object) -> bool:
    """Return True if the existing statusLine entry already points at our CLI."""
    if not isinstance(entry, dict):
        return False
    cmd = entry.get("command")
    if not isinstance(cmd, str) or not cmd.strip():
        return False
    name = Path(cmd.strip().split()[0]).name  # strip args + path
    return name in OUR_COMMAND_NAMES


def _read_settings() -> dict:
    if not SETTINGS_PATH.exists():
        return {}
    try:
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_settings(data: dict) -> bool:
    """Atomically write settings.json so we can never leave half a file behind."""
    return atomic_write_text(
        SETTINGS_PATH,
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
    )


def is_statusline_configured() -> bool:
    """Return True if settings.json already has *our* statusLine entry."""
    settings = _read_settings()
    return _is_our_statusline(settings.get("statusLine"))


def ensure_statusline_configured() -> Tuple[bool, str]:
    """Silently ensure settings.json has *our* statusLine config.

    Behavior:
      - missing       → write our config
      - foreign cmd   → leave alone (don't overwrite another tool's setup)
      - our cmd, stale path (different `command`) → refresh path
      - our cmd, current → no-op

    Returns (changed, message).
    """
    settings = _read_settings()
    existing = settings.get("statusLine")
    desired  = _statusline_config()

    if existing is None:
        settings["statusLine"] = desired
        if _write_settings(settings):
            return True, f"Added statusLine config to {SETTINGS_PATH}"
        return False, f"Could not write to {SETTINGS_PATH}"

    if not _is_our_statusline(existing):
        # Don't trample another tool's statusLine.
        cmd = existing.get("command", "?") if isinstance(existing, dict) else "?"
        return False, (
            f"settings.json already has a different statusLine command "
            f"({cmd!r}). Leaving it alone — set "
            f'"statusLine": {{"type": "command", "command": "cs"}} '
            f"manually if you want claude-statusbar."
        )

    # Ours, but possibly outdated path → refresh if it changed.
    if existing.get("command") != desired["command"]:
        settings["statusLine"] = desired
        if _write_settings(settings):
            return True, (
                f"Refreshed statusLine command path to "
                f"{desired['command']!r} in {SETTINGS_PATH}"
            )
        return False, f"Could not write to {SETTINGS_PATH}"

    return False, "statusLine already configured"


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

    for src in sorted(src_dir.glob("*.md")):
        name = src.name
        dst = COMMANDS_DIR / name
        if dst.exists() and not force:
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
    """Interactive setup: configure the statusLine and install slash commands.

    Returns exit code (0 success, 1 partial failure, 2 unrecoverable).
    """
    changed, message = ensure_statusline_configured()
    statusline_ok = changed or "already configured" in message

    if verbose:
        marker = "✓" if statusline_ok else "!"
        print(f"{marker} {message}")
        if changed:
            print("  Restart Claude Code for the status bar to appear.")
        else:
            print(f"  Settings file: {SETTINGS_PATH}")

    cmds_ok = True
    if install_cmds:
        n, skipped = install_commands()
        if verbose:
            if n:
                print(f"✓ Installed {n} slash command(s) to {COMMANDS_DIR}")
            if skipped:
                cmds_ok = False
                print(f"  Skipped (already exist with different content; use --force to overwrite):")
                for s in skipped:
                    print(f"    {s}")
            print("  Try /statusbar in Claude Code.")

    if statusline_ok and cmds_ok:
        return 0
    if statusline_ok or cmds_ok:
        return 1
    return 2
