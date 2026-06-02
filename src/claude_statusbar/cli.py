#!/usr/bin/env python3
"""CLI entry point for claude-statusbar.

Heavy imports (.core, .styles, .themes) are deferred into the branches
that actually need them, so `cs config show` and the other lightweight
subcommands don't pay the ~13ms render-path import tax.
"""
from __future__ import annotations

import sys
import os
import argparse


def _run_config_subcommand(rest):
    """Handle `cs config <action> [args...]`. Returns exit code."""
    from . import config as cfg_mod

    if not rest:
        rest = ["show"]
    action, args = rest[0], rest[1:]

    if action == "show":
        cfg = cfg_mod.load_config()
        print(f"style               = {cfg.style}")
        print(f"theme               = {cfg.theme}")
        print(f"density             = {cfg.density}")
        print(f"auto_compact_width  = {cfg.auto_compact_width or '(disabled)'}")
        print(f"show_weekly         = {cfg.show_weekly}")
        print(f"show_language       = {cfg.show_language}")
        print(f"show_cost           = {cfg.show_cost}")
        print(f"show_cache_age      = {cfg.show_cache_age}")
        print(f"show_project_branch = {cfg.show_project_branch}")
        print(f"show_ahead_behind   = {cfg.show_ahead_behind}")
        print(f"show_todos          = {cfg.show_todos}")
        print(f"show_tools          = {cfg.show_tools}")
        print(f"show_tool_rollup    = {cfg.show_tool_rollup}")
        print(f"show_agents         = {cfg.show_agents}")
        print(f"show_duration       = {cfg.show_duration}")
        print(f"show_lines          = {cfg.show_lines}")
        print(f"bar_shimmer         = {cfg.bar_shimmer}")
        print(f"cache_ttl_seconds   = {cfg.cache_ttl_seconds}")
        print(f"warning_threshold   = {cfg.warning_threshold}")
        print(f"critical_threshold  = {cfg.critical_threshold}")
        print(f"color_ok            = {cfg.color_ok or '(theme default)'}")
        print(f"color_warn          = {cfg.color_warn or '(theme default)'}")
        print(f"color_hot           = {cfg.color_hot or '(theme default)'}")
        print(f"\nfile: {cfg_mod.CONFIG_PATH}")
        return 0

    if action == "set":
        if len(args) != 2:
            print("usage: cs config set <key> <value>", file=sys.stderr)
            return 2
        key, value = args
        try:
            new_cfg = cfg_mod.set_value(key, value)
        except (KeyError, ValueError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        print(f"{key} = {getattr(new_cfg, key)}")
        return 0

    if action == "get":
        if len(args) != 1:
            print("usage: cs config get <key>", file=sys.stderr)
            return 2
        try:
            print(cfg_mod.get_value(args[0]))
        except KeyError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        return 0

    if action == "reset":
        # Delete the config file → load_config() falls back to defaults.
        # Idempotent: missing file is success.
        try:
            cfg_mod.CONFIG_PATH.unlink()
            print(f"removed {cfg_mod.CONFIG_PATH}")
        except FileNotFoundError:
            print(f"already at defaults (no {cfg_mod.CONFIG_PATH})")
        except OSError as e:
            print(f"error: could not remove {cfg_mod.CONFIG_PATH}: {e}",
                  file=sys.stderr)
            return 2
        return 0

    print(f"unknown config action: {action} (try: show / set / get / reset)",
          file=sys.stderr)
    return 2


def _run_themes_subcommand():
    from .themes import list_themes
    print("Available themes:")
    for t in list_themes():
        print(f"  {t.name:<10}  {t.description}")
    return 0


def _run_styles_subcommand():
    from .styles import list_styles
    descriptions = {
        "classic":  "原始样式（带 [bar] 与 | 分隔）",
        "capsule":  "胶囊样式 — 带底色的药丸，地铁标识感",
        "hairline": "极简线条 — 3 格小条 + 虚线分隔",
    }
    print("Available styles:")
    for name in list_styles():
        print(f"  {name:<10}  {descriptions.get(name, '')}")
    return 0


def _run_daemon_subcommand(rest):
    """Handle `cs daemon <action> [args]`. Returns exit code."""
    if not rest:
        rest = ["status"]
    action = rest[0]
    extra = rest[1:]
    from . import daemon as _d

    if action == "status":
        return _d.cmd_status()
    if action == "stop":
        return _d.cmd_stop()
    if action == "start":
        # `cs daemon start --foreground` for debugging; default detaches.
        foreground = "--foreground" in extra
        interval = _d.DEFAULT_RENDER_INTERVAL
        for i, a in enumerate(extra):
            if a == "--render-interval" and i + 1 < len(extra):
                try:
                    interval = float(extra[i + 1])
                except ValueError:
                    print(f"invalid --render-interval: {extra[i + 1]!r}", file=sys.stderr)
                    return 2
        return _d.cmd_start(detach=not foreground, render_interval=interval)
    if action == "_run":
        # Internal: child process invocation from cmd_start(detach=True).
        # Not part of the public CLI; the leading underscore signals that.
        interval = _d.DEFAULT_RENDER_INTERVAL
        for i, a in enumerate(extra):
            if a == "--render-interval" and i + 1 < len(extra):
                try:
                    interval = float(extra[i + 1])
                except ValueError:
                    pass
        return _d.run_forever(render_interval=interval)
    if action in ("install", "uninstall", "service"):
        from . import service as _svc
        if action == "install":
            ok, msg = _svc.install()
        elif action == "uninstall":
            ok, msg = _svc.uninstall()
        else:  # service → status
            ok, msg = _svc.status()
        marker = "✓" if ok else "!"
        print(f"{marker} {msg}")
        return 0 if ok else 1
    print(
        f"unknown daemon action: {action!r} "
        "(usage: cs daemon [start|stop|status|install|uninstall|service])",
        file=sys.stderr,
    )
    return 2


def main():
    """Main CLI entry point"""
    # Render fast-path: `cs render` is what Claude Code calls 60×/min when
    # the user has switched to daemon mode (`cs setup --fast`). It must
    # avoid heavy imports — argparse + the rest of the CLI only loads on
    # the inline-fallback path, deep inside render_thin.
    if len(sys.argv) >= 2 and sys.argv[1] == "render":
        from .render_thin import render
        return render()

    # Subcommands hijack argv before argparse so they coexist with flags.
    if len(sys.argv) >= 2 and sys.argv[1] in ("config", "themes", "styles", "preview", "install-commands", "install-skill", "doctor", "daemon"):
        sub = sys.argv[1]
        rest = sys.argv[2:]
        if sub == "daemon":
            return _run_daemon_subcommand(rest)
        if sub == "config":
            return _run_config_subcommand(rest)
        if sub == "themes":
            return _run_themes_subcommand()
        if sub == "styles":
            return _run_styles_subcommand()
        if sub == "preview":
            from .preview import run as run_preview
            # Disable color when stdout is redirected to a file/pipe so
            # `cs preview > out.txt` produces clean text instead of an ANSI
            # blob. NO_COLOR (any value) and --no-color also disable.
            no_color = (
                "--no-color" in rest
                or "NO_COLOR" in os.environ
                or not sys.stdout.isatty()
            )
            # Optional --theme NAME / --style NAME filter: render only the
            # requested combo instead of all 21. Accepts both `--theme nord`
            # and `--theme=nord`; rejects `--theme` with no value (silent
            # fall-through would render all 21, surprising the user).
            theme_filter = None
            style_filter = None
            i = 0
            while i < len(rest):
                tok = rest[i]
                for flag, setter in (("--theme", "theme"), ("--style", "style")):
                    if tok == flag:
                        if i + 1 >= len(rest) or rest[i + 1].startswith("--"):
                            print(f"{flag} requires a value", file=sys.stderr)
                            return 2
                        if setter == "theme":
                            theme_filter = rest[i + 1]
                        else:
                            style_filter = rest[i + 1]
                        i += 2
                        break
                    if tok.startswith(flag + "="):
                        val = tok[len(flag) + 1:]
                        if not val:
                            print(f"{flag}= requires a value", file=sys.stderr)
                            return 2
                        if setter == "theme":
                            theme_filter = val
                        else:
                            style_filter = val
                        i += 1
                        break
                else:
                    i += 1
            return run_preview(
                use_color=not no_color,
                theme_filter=theme_filter,
                style_filter=style_filter,
            )
        if sub == "doctor":
            from .doctor import run as run_doctor
            return run_doctor()
        if sub == "install-commands":
            from .setup import install_commands, install_skills, COMMANDS_DIR, SKILLS_DIR
            force = "--force" in rest
            n, skipped = install_commands(force=force)
            print(f"Installed {n} slash command(s) to {COMMANDS_DIR}")
            if skipped:
                print("Skipped:")
                for s in skipped:
                    print(f"  {s}")
                print("Use `cs install-commands --force` to overwrite.")
            s_n, s_skipped = install_skills(force=force)
            if s_n:
                print(f"Installed {s_n} skill(s) to {SKILLS_DIR}")
            if s_skipped:
                print("Skill skipped:")
                for s in s_skipped:
                    print(f"  {s}")
            print("Try /statusbar in Claude Code, or just say `switch theme to nord`.")
            return 0
        if sub == "install-skill":
            from .setup import install_skills, SKILLS_DIR
            force = "--force" in rest
            n, skipped = install_skills(force=force)
            print(f"Installed {n} skill(s) to {SKILLS_DIR}")
            if skipped:
                print("Skipped:")
                for s in skipped:
                    print(f"  {s}")
                print("Use `cs install-skill --force` to overwrite.")
            print("Try saying `switch theme to nord` in Claude Code.")
            return 0

    parser = argparse.ArgumentParser(
        description="Claude Status Bar Monitor - Lightweight token usage monitor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  cs                            # Show current status (uses configured style+theme)
  cs --style capsule            # Override style for one render
  cs --theme twilight           # Override theme
  cs config show                # Show current config
  cs config set style hairline  # Persist style
  cs config set theme linen     # Persist theme
  cs themes                     # List available themes
  cs styles                     # List available styles
  cs preview                    # Render every style × theme together
  cs install-commands           # Install /statusbar slash commands
  cs --json-output              # Machine-readable JSON

Integration:
  tmux:     set -g status-right '#(claude-statusbar)'
  zsh:      RPROMPT='$(claude-statusbar)'
        """,
    )

    # `from . import __version__` triggers importlib.metadata, which pulls
    # email.message + zipfile + ~20ms of cumulative imports on every render.
    # Only register the action when the user actually asked for --version.
    if "--version" in sys.argv[1:]:
        from . import __version__ as _ver
        parser.add_argument(
            "--version", action="version", version=f"%(prog)s {_ver}"
        )

    parser.add_argument(
        "--setup",
        action="store_true",
        help="Configure ~/.claude/settings.json to show the status bar in Claude Code",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help=argparse.SUPPRESS,  # daemon mode is the default since 3.6.0
    )
    parser.add_argument(
        "--inline",
        action="store_true",
        help=(
            "When used with --setup, opt out of daemon mode and use the "
            "legacy inline path (no background daemon). Higher per-tick CPU."
        ),
    )
    parser.add_argument(
        "--project",
        type=str,
        nargs="?",
        const=".",
        default=None,
        metavar="PATH",
        help=(
            "When used with --setup, write a project-level "
            ".claude/settings.json (in PATH, or the current directory if "
            "no path is given) that overrides the global statusLine. Use "
            "this when another tool keeps reclaiming the user-level slot."
        ),
    )
    parser.add_argument(
        "--install-deps",
        action="store_true",
        help="Install claude-monitor dependency for full functionality",
    )
    parser.add_argument(
        "--json-output",
        action="store_true",
        help="Emit machine-readable JSON instead of colored status line",
    )
    parser.add_argument(
        "--reset-hour",
        type=int,
        help="Reset hour (0-23) if your quota resets at a fixed local time",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI color codes in output",
    )
    parser.add_argument(
        "--detail",
        action="store_true",
        help="Show detailed breakdown of usage data and limits",
    )
    parser.add_argument(
        "--plan",
        type=str,
        help=(
            "(Deprecated) Kept for compatibility with older scripts. "
            "Plan tier is now derived from official rate-limit headers."
        ),
    )
    parser.add_argument(
        "--no-auto-update",
        action="store_true",
        help="Disable automatic update checks (or set CLAUDE_STATUSBAR_NO_UPDATE=1)",
    )
    parser.add_argument(
        "--warning-threshold",
        type=float,
        help="Usage percentage that switches from green to yellow (default: 30)",
    )
    parser.add_argument(
        "--critical-threshold",
        type=float,
        help="Usage percentage that switches from yellow to red (default: 70)",
    )
    # Defer the imports for choices generation so subcommands that don't
    # touch argparse (config / themes / styles / preview) skip them entirely.
    from .styles import list_styles as _list_styles
    from .themes import list_themes as _list_themes
    parser.add_argument(
        "--style",
        type=str,
        choices=_list_styles(),
        help="Override status-line style for this run (persist with `cs config set style`)",
    )
    parser.add_argument(
        "--theme",
        type=str,
        choices=[t.name for t in _list_themes()],
        help="Override color theme for this run (persist with `cs config set theme`)",
    )

    args = parser.parse_args()

    # --project only makes sense with --setup; rejecting up-front prevents
    # the silent no-op of `cs --project foo` (which would otherwise render
    # the bar and discard the flag).
    if args.project is not None and not args.setup:
        parser.error("--project requires --setup")

    if sys.version_info < (3, 9):
        print(
            "claude-statusbar requires Python 3.9+; please upgrade your interpreter.",
            file=sys.stderr,
        )
        return 1

    def env_bool(name: str) -> bool:
        val = os.environ.get(name)
        return val is not None and val.lower() in ("1", "true", "yes", "y", "on")

    def env_float(name: str) -> float | None:
        val = os.environ.get(name)
        if val is None or val == "":
            return None
        try:
            return float(val)
        except ValueError:
            print(
                f"Ignoring invalid {name} (must be a number between 0 and 100).",
                file=sys.stderr,
            )
            return None

    # NO_COLOR follows the no-color.org convention: ANY value (including
    # empty string) disables color. So we check presence, not truthiness.
    no_color_env = "NO_COLOR" in os.environ

    json_output = args.json_output or env_bool("CLAUDE_STATUSBAR_JSON")
    reset_hour = args.reset_hour
    if reset_hour is None:
        env_reset = os.environ.get("CLAUDE_RESET_HOUR")
        if env_reset:
            try:
                reset_hour = int(env_reset)
            except ValueError:
                print(
                    "Ignoring invalid CLAUDE_RESET_HOUR (must be integer 0-23).",
                    file=sys.stderr,
                )
                reset_hour = None
    if reset_hour is not None and not (0 <= reset_hour <= 23):
        print("Reset hour must be between 0 and 23.", file=sys.stderr)
        return 1

    if args.setup:
        from .setup import run_setup
        # Daemon (fast) mode is the default since 3.6.0; --inline opts out.
        # Keep the legacy --fast flag accepted (no-op) so existing scripts work.
        fast = not args.inline
        if args.project is not None:
            from pathlib import Path
            from .setup import ensure_project_statusline_configured
            ok, msg = ensure_project_statusline_configured(
                Path(args.project), fast=fast
            )
            done = ok or "already configured" in msg
            print(f"{'✓' if done else '!'} {msg}")
            if ok:
                print("  Restart Claude Code in this directory for the override to take effect.")
            return 0 if done else 1
        return run_setup(verbose=True, fast=fast)

    if args.install_deps:
        print("Installing claude-monitor for full functionality...")
        print("Run one of these commands:")
        print("  uv tool install claude-monitor    # Recommended")
        print("  pip install claude-monitor")
        print("  pipx install claude-monitor")
        return 0

    # `--plan` was removed in 1.4.0 but kept as a no-op so old scripts don't
    # explode with "unrecognized argument". Nothing reads its value.
    _ = args.plan

    if args.no_auto_update:
        os.environ['CLAUDE_STATUSBAR_NO_UPDATE'] = '1'

    # Run the status bar
    use_color = not (args.no_color or no_color_env)
    from .progress import normalize_thresholds  # heavy: pulls in all of progress
    try:
        warning_threshold, critical_threshold = normalize_thresholds(
            args.warning_threshold
            if args.warning_threshold is not None
            else env_float("CLAUDE_STATUSBAR_WARNING_THRESHOLD"),
            args.critical_threshold
            if args.critical_threshold is not None
            else env_float("CLAUDE_STATUSBAR_CRITICAL_THRESHOLD"),
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    try:
        # Pull in the heavy render path only now (after we've definitely
        # decided to render — subcommands have already returned by here).
        from .core import main as statusbar_main
        statusbar_main(
            json_output=json_output,
            reset_hour=reset_hour,
            use_color=use_color,
            detail=args.detail,
            warning_threshold=warning_threshold,
            critical_threshold=critical_threshold,
            style_override=args.style,
            theme_override=args.theme,
        )
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
