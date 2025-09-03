#!/usr/bin/env python3
"""CLI entry point for claude-statusbar"""

import sys
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
  
Integration:
  tmux:     set -g status-right '#(claude-statusbar)'
  zsh:      RPROMPT='$(claude-statusbar)'
  i3:       status_command echo "$(claude-statusbar)"
        """
    )
    
    parser.add_argument(
        '--version', 
        action='version', 
        version='%(prog)s 1.2.1'
    )
    
    parser.add_argument(
        '--install-deps',
        action='store_true',
        help='Install claude-monitor dependency for full functionality'
    )
    
    args = parser.parse_args()
    
    if args.install_deps:
        print("Installing claude-monitor for full functionality...")
        print("Run one of these commands:")
        print("  uv tool install claude-monitor    # Recommended")
        print("  pip install claude-monitor")
        print("  pipx install claude-monitor")
        return 0
    
    # Run the status bar
    try:
        statusbar_main()
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

if __name__ == '__main__':
    sys.exit(main())