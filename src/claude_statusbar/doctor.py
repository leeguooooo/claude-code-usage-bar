"""`cs doctor` — self-diagnostic.

When a user opens an issue saying "the status bar doesn't work", they are
almost never able to grep their config or trace import paths. The output
of `cs doctor` is the one thing they can paste verbatim that lets us help
them in seconds:

  - which `cs` are they running, and from where
  - did Claude Code actually wire up our statusLine entry
  - is fresh stdin landing in the cache
  - which terminal / size are they on
  - what style + theme do they have configured

Everything is read-only and best-effort. A failure on any line should not
prevent the rest from rendering.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any


def _green(s: str) -> str:  return f"\x1b[32m{s}\x1b[0m" if _ansi_ok() else s
def _red(s: str)   -> str:  return f"\x1b[31m{s}\x1b[0m" if _ansi_ok() else s
def _dim(s: str)   -> str:  return f"\x1b[2m{s}\x1b[0m"  if _ansi_ok() else s


def _ansi_ok() -> bool:
    if "NO_COLOR" in os.environ:
        return False
    return sys.stdout.isatty()


def _line(label: str, value: Any, *, ok: bool = True) -> None:
    mark = _green("✓") if ok else _red("✗")
    print(f"  {mark} {label:<22} {value}")


def _safe(thunk):
    try:
        return thunk()
    except Exception as e:
        return f"<error: {type(e).__name__}: {e}>"


def run() -> int:
    print()
    print("  cs doctor — claude-statusbar self-check")
    print(f"  {_dim('─' * 60)}")

    # --- which cs ---
    cs_path = (
        shutil.which("cs")
        or shutil.which("cstatus")
        or shutil.which("claude-statusbar")
    )
    _line("cs binary",
          cs_path or _red("(not on PATH — Claude Code statusLine may fail)"),
          ok=cs_path is not None)

    # --- version ---
    try:
        from claude_statusbar import __version__
        _line("version", __version__)
    except Exception as e:
        _line("version", _red(str(e)), ok=False)

    # --- python ---
    _line("python", f"{sys.version.split()[0]}  ({sys.executable})")

    # --- ~/.claude/settings.json statusLine entry ---
    settings_path = Path.home() / ".claude" / "settings.json"
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            _line("settings.json", _red(f"unreadable: {e}"), ok=False)
            settings = {}
        sl = settings.get("statusLine") if isinstance(settings, dict) else None
        if isinstance(sl, dict) and sl.get("command"):
            cmd = sl["command"]
            from .setup import _is_our_statusline
            ours = _is_our_statusline(sl)
            _line("statusLine entry",
                  f"{cmd}  {_green('(ours)') if ours else _red('(not ours)')}",
                  ok=ours)
        else:
            _line("statusLine entry",
                  _red("missing — run: cs --setup"), ok=False)
    else:
        _line("settings.json",
              _red(f"missing — run: cs --setup ({settings_path})"), ok=False)

    # --- last_stdin.json freshness ---
    cache = Path.home() / ".cache" / "claude-statusbar" / "last_stdin.json"
    if cache.exists():
        age_s = _dt.datetime.now().timestamp() - cache.stat().st_mtime
        if age_s < 60:
            label = f"{int(age_s)}s ago"
            ok = True
        elif age_s < 3600:
            label = f"{int(age_s/60)}m ago"
            ok = True
        elif age_s < 86400:
            label = f"{int(age_s/3600)}h ago"
            ok = True
        else:
            label = _red(f"{int(age_s/86400)}d ago — Claude Code hasn't pushed lately")
            ok = False
        _line("last_stdin cache", f"{label}  ({cache})", ok=ok)
    else:
        _line("last_stdin cache",
              _dim("not yet — Claude Code hasn't pushed any payload"))

    # --- terminal ---
    try:
        size = os.get_terminal_size()
        _line("terminal", f"{size.columns}×{size.lines}  TERM={os.environ.get('TERM', '?')}")
    except OSError:
        _line("terminal", _dim("(no tty — likely piped)"))

    # --- config ---
    try:
        from . import config as cfg_mod
        cfg = cfg_mod.load_config()
        _line("style", cfg.style)
        _line("theme", cfg.theme)
        _line("density", cfg.density)
        _line("show_cost", cfg.show_cost)
        _line("show_weekly", cfg.show_weekly)
        _line("show_language", cfg.show_language)
        if cfg.auto_compact_width:
            _line("auto_compact_width", cfg.auto_compact_width)
        _line("config file",
              cfg_mod.CONFIG_PATH if cfg_mod.CONFIG_PATH.exists() else
              _dim(f"{cfg_mod.CONFIG_PATH} (defaults — not created yet)"))
    except Exception as e:
        _line("config", _red(str(e)), ok=False)

    # --- slash commands ---
    cmds_dir = Path.home() / ".claude" / "commands"
    if cmds_dir.is_dir():
        ours = sorted(p.name for p in cmds_dir.glob("statusbar*.md"))
        _line("slash commands",
              f"{len(ours)} installed  ({', '.join(ours) if ours else 'none'})",
              ok=bool(ours))
    else:
        _line("slash commands",
              _dim(f"{cmds_dir} not present — run: cs install-commands"))

    print()
    return 0
