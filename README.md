# Claude Status Bar

🔋 Lightweight status bar for Claude AI token usage in your terminal.

![Status Example](https://img.shields.io/badge/Status-🔋_T:48k%2F133k_%7C_$59%2F119_%7C_⏱️31m_%7C_50%25-yellow)

## ✨ One-Line Install

```bash
curl -fsSL https://raw.githubusercontent.com/leeguooooo/claude-code-usage-bar/main/web-install.sh | bash
```

This automatically:
- ✅ Installs the package
- ✅ Configures Claude Code status bar
- ✅ Sets up shell aliases
- ✅ Just restart Claude Code and you're done!

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

## 📄 License

MIT

---

*Built on [Claude Monitor](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor) by [@Maciek-roboblog](https://github.com/Maciek-roboblog)*