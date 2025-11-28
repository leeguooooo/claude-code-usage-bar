#!/usr/bin/env python3
"""CLI entry point for claude-statusbar"""

import sys
import os
import argparse
from .core import main as statusbar_main

def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description='Claude Status Bar Monitor - Lightweight token usage monitor',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  claude-statusbar          # Show current usage
  cstatus                   # Short alias
  cs                        # Shortest alias
  
  claude-statusbar --json-output
  claude-statusbar --plan zai-pro
  claude-statusbar --reset-hour 14
  
Integration:
  tmux:     set -g status-right '#(claude-statusbar)'
  zsh:      RPROMPT='$(claude-statusbar)'
  i3:       status_command echo "$(claude-statusbar)"
        """
    )
    
    parser.add_argument(
        '--version', 
        action='version', 
        version='%(prog)s 1.3.0'
    )
    
    parser.add_argument(
        '--install-deps',
        action='store_true',
        help='Install claude-monitor dependency for full functionality'
    )
    parser.add_argument(
        '--json-output',
        action='store_true',
        help='Emit machine-readable JSON instead of colored status line'
    )
    parser.add_argument(
        '--plan',
        type=str,
        help='Plan override (e.g., pro, max5, max20, zai-lite, zai-pro, zai-max)'
    )
    parser.add_argument(
        '--reset-hour',
        type=int,
        help='Reset hour (0-23) if your quota resets at a fixed local time'
    )
    
    args = parser.parse_args()

    if sys.version_info < (3, 9):
        print("claude-statusbar requires Python 3.9+; please upgrade your interpreter.", file=sys.stderr)
        return 1

    def env_bool(name: str) -> bool:
        val = os.environ.get(name)
        return val is not None and val.lower() in ("1", "true", "yes", "y", "on")

    # Prefer CLI, fall back to env
    plan = args.plan or os.environ.get("CLAUDE_PLAN")
    json_output = args.json_output or env_bool("CLAUDE_STATUSBAR_JSON")
    reset_hour = args.reset_hour
    if reset_hour is None:
        env_reset = os.environ.get("CLAUDE_RESET_HOUR")
        if env_reset:
            try:
                reset_hour = int(env_reset)
            except ValueError:
                print("Ignoring invalid CLAUDE_RESET_HOUR (must be integer 0-23).", file=sys.stderr)
                reset_hour = None
    if reset_hour is not None and not (0 <= reset_hour <= 23):
        print("Reset hour must be between 0 and 23.", file=sys.stderr)
        return 1
    
    if args.install_deps:
        print("Installing claude-monitor for full functionality...")
        print("Run one of these commands:")
        print("  uv tool install claude-monitor    # Recommended")
        print("  pip install claude-monitor")
        print("  pipx install claude-monitor")
        return 0
    
    # Run the status bar
    try:
        statusbar_main(json_output=json_output, plan=plan, reset_hour=reset_hour)
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

if __name__ == '__main__':
    sys.exit(main())
