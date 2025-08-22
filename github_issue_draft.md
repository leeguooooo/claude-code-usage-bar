# GitHub Issue Draft for Claude-Code-Usage-Monitor

## Title: Created a lightweight status bar companion tool

## Body:

Hi @Maciek-roboblog! 👋

First, thank you for creating such an excellent monitoring tool! Your claude-monitor package has been incredibly helpful for tracking AI usage.

I wanted to share a companion tool I've built that leverages your package:

### 🔋 claude-statusbar
A lightweight status bar display specifically designed for terminal and IDE integration.

- **GitHub**: https://github.com/leeguooooo/claude-code-usage-bar
- **PyPI**: https://pypi.org/project/claude-statusbar/
- **Purpose**: Minimal status bar display that shows token usage in a compact format

### How it complements your project:
- Uses `claude-monitor` as a dependency for all the heavy lifting (data analysis, P90 calculations, etc.)
- Focuses solely on providing a lightweight display output
- One-line installation that auto-configures everything
- Designed for users who want quick status bar integration

### Key differences:
- Your project: Full-featured monitoring with Rich UI, detailed analytics, and comprehensive tracking
- This project: Minimal single-line output optimized for status bars (tmux, terminal prompts, IDEs)

### Attribution:
- README clearly credits your project as the foundation
- Recommends installing claude-monitor for full functionality
- Links back to your repository

This is intentionally kept as a separate, focused tool rather than a PR, as it serves a different use case (minimal display vs. full monitoring).

If you're interested, I'd be happy to:
1. Add any additional attribution you'd prefer
2. Coordinate on any shared improvements
3. Help users discover both tools for their different needs

Thanks again for your amazing work on the original monitor!

Best regards,
@leeguooooo