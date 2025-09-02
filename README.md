# Claude Status Bar

🔋 Lightweight status bar for Claude AI token usage in your terminal.

![Claude Code Status Bar](https://raw.githubusercontent.com/leeguooooo/claude-code-usage-bar/main/img.png)

## ✨ One-Line Install

```bash
curl -fsSL "https://raw.githubusercontent.com/leeguooooo/claude-code-usage-bar/main/web-install.sh?v=$(date +%s)" | bash
```

> 💡 The `?v=$(date +%s)` parameter ensures you get the latest version without CDN caching issues.

**If you still see old version, try with additional cache-busting:**
```bash
curl -fsSL -H "Cache-Control: no-cache" "https://raw.githubusercontent.com/leeguooooo/claude-code-usage-bar/main/web-install.sh?v=$(date +%s)&r=$RANDOM" | bash
```

This automatically:
- ✅ Installs the package
- ✅ Configures Claude Code status bar
- ✅ Sets up shell aliases
- ✅ Just restart Claude Code and you're done!

> 💡 **After installation:** Restart Claude Code and say something to see your usage!

## 📦 Alternative Install Methods

```bash
# PyPI
pip install claude-statusbar

# uv (fast)
uv tool install claude-statusbar

# pipx (isolated)
pipx install claude-statusbar
```

## 🚀 Usage

```bash
claude-statusbar  # or cs for short
```

Output: `🔋 T:48.0k/133.3k | $:59.28/90.26 | 🤖opusplan | ⏱️31m | Usage:16.5%`

- **T**: Token usage (current/limit)
- **$**: Cost in USD (dynamic P90 limits)
- **🤖**: Current Claude model
- **⏱️**: Time until reset
- **Usage %**: Cost-based percentage, color-coded (🟢 <30% | 🟡 30-70% | 🔴 >70%)

## 🔧 Integrations

**tmux status bar:**
```bash
set -g status-right '#(claude-statusbar)'
```

**zsh prompt:**
```bash
RPROMPT='$(claude-statusbar)'
```

## 🔄 Upgrading

### Automatic Updates (Recommended)
The tool automatically checks for updates once per day and upgrades itself. No action needed! 🎉

When an update is available, you'll see: `🔄 Upgraded from v1.0.0 to v1.1.0`

### Manual Upgrade
If automatic upgrade fails, you can manually update:

```bash
# Re-run the installer (recommended - always gets latest)
curl -fsSL "https://raw.githubusercontent.com/leeguooooo/claude-code-usage-bar/main/web-install.sh?v=$(date +%s)" | bash

# Or upgrade via package manager:
# If installed with pip
pip install --upgrade claude-statusbar

# If installed with pipx  
pipx upgrade claude-statusbar

# If installed with uv
uv tool upgrade claude-statusbar
```

**Note:** After upgrading, restart Claude Code to use the new version.

## 💖 Support

If you find this tool helpful, consider:
- ⭐ Star this repo
- 💖 Sponsor via GitHub
- 🐛 Report issues

## 📄 License

MIT

## ⭐ Star History

[![Star History Chart](https://api.star-history.com/svg?repos=leeguooooo/claude-code-usage-bar&type=Date)](https://star-history.com/#leeguooooo/claude-code-usage-bar&Date)

---

*Built on [Claude Monitor](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor) by [@Maciek-roboblog](https://github.com/Maciek-roboblog)*