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


def _render_argv() -> list:
    """The argv Claude Code's statusLine effectively runs.

    Frozen binaries dispatch subcommands directly (`sys.executable` *is* `cs`);
    pip/uv installs go through `-m`, matching the self-spawn convention in
    daemon.py and cli.py.
    """
    if getattr(sys, "frozen", False):
        return [sys.executable, "render"]
    return [sys.executable, "-m", "claude_statusbar.cli", "render"]


def _render_smoke_test(cache: Path) -> None:
    """Actually render, using the real cached payload, and report if it dies.

    Every other check here inspects *state* — all of them can be green while the
    render path itself is broken. That is exactly what happened in issue #36: the
    standalone binary raised ValueError on every tick once a session was cached,
    the status line vanished in Claude Code, and `cs doctor` still reported all
    green because it never rendered anything.

    The empty-stdin render some earlier checks imply is not enough either — the
    crash only surfaced with a realistic payload, because the cached meta needs a
    `daemon_started_at` field to reach the code-drift check. So feed the genuine
    `last_stdin.json` through a real subprocess.

    Side effect: this is a normal status-line tick, so it refreshes the session
    bucket and may lazily spawn the daemon, exactly as Claude Code's own ticks do.
    """
    import subprocess

    if not cache.exists():
        _line("render smoke test", _dim("skipped — no cached payload yet"))
        return
    try:
        payload = cache.read_bytes()
    except OSError as e:
        _line("render smoke test", _dim(f"skipped — cache unreadable: {e}"))
        return

    try:
        proc = subprocess.run(_render_argv(), input=payload,
                              capture_output=True, timeout=30)
    except Exception as e:
        _line("render smoke test",
              _red(f"could not run: {type(e).__name__}: {e}"), ok=False)
        return

    stderr = (proc.stderr or b"").decode("utf-8", "replace").strip()
    if proc.returncode != 0:
        tail = stderr.splitlines()[-1] if stderr else f"exit {proc.returncode}"
        _line("render smoke test", _red(f"CRASHED — {tail}"), ok=False)
        for ln in stderr.splitlines()[-15:]:
            print(f"      {_dim(ln)}")
        print(f"      {_dim('please paste this into an issue: ' + _ISSUES_URL)}")
        return

    out = (proc.stdout or b"").decode("utf-8", "replace")
    if not out.strip():
        _line("render smoke test",
              _red("rendered nothing — status line would be blank"), ok=False)
        return
    _line("render smoke test", f"ok — {len(out)} bytes rendered")


def _statusline_shell_check(cmd: str, cache: Path) -> None:
    """Exec the *configured* settings.json command string through `sh`.

    The render smoke test above builds its own argv, so it stays green even
    when the configured string itself is shell-dead — exactly issue #42: a
    backslash Windows path passes every filesystem check, but Claude Code
    runs the statusLine string through Git Bash's sh, which eats the
    backslashes (`C:\\Users\\me\\cs.EXE` → `C:Usersmecs.EXE`, exit 127).
    This check runs what Claude Code actually runs.
    """
    import subprocess

    if os.name == "nt" and "\\" in cmd:
        # No need to exec anything — sh will mangle this before the OS ever
        # sees a path. Diagnosable statically.
        _line("statusLine shell test",
              _red("backslash path — Git Bash eats `\\` before exec; "
                   "run: cs --setup"), ok=False)
        return

    sh = shutil.which("sh")
    if sh is None:
        _line("statusLine shell test",
              _dim("skipped — no sh on PATH to emulate Claude Code's exec"))
        return

    payload = b"{}"
    try:
        if cache.exists():
            payload = cache.read_bytes()
    except OSError:
        pass

    try:
        proc = subprocess.run([sh, "-c", cmd], input=payload,
                              capture_output=True, timeout=30)
    except Exception as e:
        _line("statusLine shell test",
              _red(f"could not run: {type(e).__name__}: {e}"), ok=False)
        return

    if proc.returncode != 0:
        stderr = (proc.stderr or b"").decode("utf-8", "replace").strip()
        tail = stderr.splitlines()[-1] if stderr else f"exit {proc.returncode}"
        _line("statusLine shell test",
              _red(f"exit {proc.returncode} — {tail}"), ok=False)
        print(f"      {_dim('the configured command fails in the shell Claude Code uses')}")
        return
    if not (proc.stdout or b"").strip():
        _line("statusLine shell test",
              _red("rendered nothing — status line would be blank"), ok=False)
        return
    _line("statusLine shell test", "ok — configured command renders via sh")


_ISSUES_URL = "https://github.com/leeguooooo/claude-code-usage-bar/issues"


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
    sl_cmd = None  # set when the entry is ours; drives the shell test below
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
            from .setup import _is_our_statusline, _existing_uses_render
            ours = _is_our_statusline(sl)
            if ours:
                sl_cmd = cmd
            _line("statusLine entry",
                  f"{cmd}  {_green('(ours)') if ours else _red('(not ours)')}",
                  ok=ours)
            # Phase B/C upsell: at refreshInterval=1 the inline command
            # burns ~4% CPU continuously; fast mode drops it to ~1%.
            try:
                ri = sl.get("refreshInterval")
                if (isinstance(ri, (int, float)) and ri <= 2 and ours
                        and not _existing_uses_render(sl)):
                    _line("perf hint",
                          _dim(f"refreshInterval={ri}s with inline `cs`. "
                               f"Run `cs --setup --fast` for ~5x lower CPU "
                               f"(daemon mode). See README → Fast mode."))
            except (TypeError, ValueError):
                pass
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

    # --- 5h/7d quota cache freshness ---
    # The single most-reported "my bars disappeared" cause: the statusLine got
    # displaced (or the daemon died), cs stopped receiving rate_limits, and the
    # cached windows expired — so the expiry guard hid the bars. Surface it here
    # with the fix instead of making users diff cache files by hand.
    try:
        from .predict import quota_cache_status
        _qs, _qage = quota_cache_status()
        if _qs == "stale":
            age_txt = f"{int(_qage/3600)}h" if _qage and _qage >= 3600 else (
                f"{int(_qage/60)}m" if _qage else "?")
            _line("5h/7d quota cache",
                  _red(f"stale (last update {age_txt} ago, resets expired) — "
                       f"restart Claude Code to refresh; if it keeps happening "
                       f"another tool took the statusLine → run cs --setup"),
                  ok=False)
        elif _qs == "fresh":
            _line("5h/7d quota cache", "fresh")
        else:
            _line("5h/7d quota cache",
                  _dim("empty — no quota recorded yet (new account / relay)"))
    except Exception:
        pass

    # --- daemon (Phase B+) ---
    try:
        from . import daemon as _d
        pid = _d.read_pidfile()
        if pid is None:
            _line("daemon", _dim("not running (statusLine in inline mode — fine, but slower)"))
        elif _d.is_alive(pid):
            sids = _d._active_sessions()
            if not sids:
                _line("daemon", f"pid {pid} alive  (no active sessions yet)", ok=True)
            else:
                # Summarise across all per-session buckets (v3.3.0+).
                ages = []
                stale_count = 0
                for sid in sids:
                    try:
                        meta = json.loads(_d.session_meta_path(sid).read_text(encoding="utf-8"))
                        age = _dt.datetime.now().timestamp() - float(meta.get("generated_at", 0))
                        ages.append(age)
                        if age > _d.META_STALE_AFTER:
                            stale_count += 1
                    except (OSError, ValueError, json.JSONDecodeError):
                        stale_count += 1
                if stale_count == 0 and ages:
                    _line("daemon", f"pid {pid} alive  {len(sids)} session(s)  freshest {min(ages):.1f}s", ok=True)
                else:
                    _line("daemon", _red(f"pid {pid} alive  {len(sids)} session(s)  {stale_count} STALE"), ok=False)
        else:
            _line("daemon", _red(f"pidfile says {pid} but process is gone — run: cs daemon stop"), ok=False)
    except Exception as e:
        _line("daemon", _dim(f"check skipped: {e}"))

    # --- launchd / systemd service (Phase C) ---
    try:
        from . import service as _svc
        ok, msg = _svc.status()
        if ok:
            _line("service", msg, ok=True)
        else:
            _line("service", _dim(msg))
    except Exception as e:
        _line("service", _dim(f"check skipped: {e}"))

    # --- render smoke test ---
    # Last of the health checks, and the only one that proves the render path
    # actually works rather than merely inspecting state around it.
    try:
        _render_smoke_test(cache)
    except Exception as e:  # doctor must never die on its own check
        _line("render smoke test", _dim(f"check skipped: {e}"))

    # --- statusLine shell test ---
    # The smoke test proves *our code* renders; this proves the *configured
    # command string* survives the shell Claude Code execs it through.
    try:
        if sl_cmd:
            _statusline_shell_check(sl_cmd, cache)
    except Exception as e:
        _line("statusLine shell test", _dim(f"check skipped: {e}"))

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
        _line("show_balance", cfg.show_balance)
        _line("balance_bar", cfg.balance_bar)
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
