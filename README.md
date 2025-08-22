# Claude Status Bar

🔋 Lightweight status bar for Claude AI token usage in your terminal.

![Claude Code Status Bar](https://raw.githubusercontent.com/leeguooooo/claude-code-usage-bar/main/img.png)

## ✨ One-Line Install

```bash
curl -fsSL https://raw.githubusercontent.com/leeguooooo/claude-code-usage-bar/main/web-install.sh | bash
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

Output: `🔋 T:48.0k/133.3k | $:59.28/119 | ⏱️31m | Usage:50%`

- **T**: Token usage (current/limit)
- **$**: Cost in USD
- **⏱️**: Time until reset
- **Usage %**: Color-coded (🟢 <30% | 🟡 30-70% | 🔴 >70%)

## 🔧 Integrations

**tmux status bar:**
```bash
set -g status-right '#(claude-statusbar)'
```

**zsh prompt:**
```bash
RPROMPT='$(claude-statusbar)'
```

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