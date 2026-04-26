#!/usr/bin/env python3
"""CLI entry point for claude-statusbar"""

import sys
import os
import argparse
from . import __version__
from .core import main as statusbar_main
from .progress import normalize_thresholds
from .styles import list_styles
from .themes import list_themes


def _run_config_subcommand(rest):
    """Handle `cs config <action> [args...]`. Returns exit code."""
    from . import config as cfg_mod

    if not rest:
        rest = ["show"]
    action, args = rest[0], rest[1:]

    if action == "show":
        cfg = cfg_mod.load_config()
        print(f"style              = {cfg.style}")
        print(f"theme              = {cfg.theme}")
        print(f"density            = {cfg.density}")
        print(f"auto_compact_width = {cfg.auto_compact_width or '(disabled)'}")
        print(f"show_pet           = {cfg.show_pet}")
        print(f"show_weekly        = {cfg.show_weekly}")
        print(f"show_language      = {cfg.show_language}")
        print(f"warning_threshold  = {cfg.warning_threshold}")
        print(f"critical_threshold = {cfg.critical_threshold}")
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

    print(f"unknown config action: {action} (try: show / set / get)", file=sys.stderr)
    return 2


def _run_themes_subcommand():
    print("Available themes:")
    for t in list_themes():
        print(f"  {t.name:<10}  {t.description}")
    return 0


def _run_styles_subcommand():
    descriptions = {
        "classic":  "原始样式（带 [bar] 与 | 分隔）",
        "capsule":  "胶囊样式 — 带底色的药丸，地铁标识感",
        "hairline": "极简线条 — 3 格小条 + 虚线分隔",
    }
    print("Available styles:")
    for name in list_styles():
        print(f"  {name:<10}  {descriptions.get(name, '')}")
    return 0


def main():
    """Main CLI entry point"""
    # Subcommands hijack argv before argparse so they coexist with flags.
    if len(sys.argv) >= 2 and sys.argv[1] in ("config", "themes", "styles", "preview", "install-commands"):
        sub = sys.argv[1]
        rest = sys.argv[2:]
        if sub == "config":
            return _run_config_subcommand(rest)
        if sub == "themes":
            return _run_themes_subcommand()
        if sub == "styles":
            return _run_styles_subcommand()
        if sub == "preview":
            from .preview import run as run_preview
            no_color = "--no-color" in rest or os.environ.get("NO_COLOR") not in (None, "")
            return run_preview(use_color=not no_color)
        if sub == "install-commands":
            from .setup import install_commands, COMMANDS_DIR
            force = "--force" in rest
            n, skipped = install_commands(force=force)
            print(f"Installed {n} slash command(s) to {COMMANDS_DIR}")
            if skipped:
                print("Skipped:")
                for s in skipped:
                    print(f"  {s}")
                print("Use `cs install-commands --force` to overwrite.")
            print("Try /statusbar in Claude Code.")
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

    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )

    parser.add_argument(
        "--setup",
        action="store_true",
        help="Configure ~/.claude/settings.json to show the status bar in Claude Code",
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
        "--pet-name",
        type=str,
        help="Set a custom name for the status bar pet (default: random per session)",
    )
    parser.add_argument(
        "--hide-pet",
        action="store_true",
        help="Hide the status bar pet (or set CLAUDE_STATUSBAR_HIDE_PET=1)",
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
    parser.add_argument(
        "--style",
        type=str,
        choices=list_styles(),
        help="Override status-line style for this run (persist with `cs config set style`)",
    )
    parser.add_argument(
        "--theme",
        type=str,
        choices=[t.name for t in list_themes()],
        help="Override color theme for this run (persist with `cs config set theme`)",
    )

    args = parser.parse_args()

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
        return run_setup(verbose=True)

    if args.install_deps:
        print("Installing claude-monitor for full functionality...")
        print("Run one of these commands:")
        print("  uv tool install claude-monitor    # Recommended")
        print("  pip install claude-monitor")
        print("  pipx install claude-monitor")
        return 0

    if args.plan is not None:
        # Compatibility shim for scripts that still pass --plan.
        # Current implementation no longer needs a local plan override.
        os.environ["CLAUDE_PLAN"] = args.plan

    if args.no_auto_update:
        os.environ['CLAUDE_STATUSBAR_NO_UPDATE'] = '1'

    # Run the status bar
    use_color = not (args.no_color or env_bool("NO_COLOR"))
    show_pet = not (args.hide_pet or env_bool("CLAUDE_STATUSBAR_HIDE_PET"))
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
        pet_name = args.pet_name or os.environ.get("CLAUDE_PET_NAME")
        statusbar_main(
            json_output=json_output,
            reset_hour=reset_hour,
            use_color=use_color,
            detail=args.detail,
            pet_name=pet_name,
            show_pet=show_pet,
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
