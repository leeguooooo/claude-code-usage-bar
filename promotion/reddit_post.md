# Reddit Post Templates

## r/ClaudeAI Post

**Title:** Made a lightweight status bar to track Claude token usage in real-time

**Body:**
Hey everyone! 👋

Like many of you, I kept running out of Claude tokens unexpectedly. The web UI doesn't show real-time usage, and checking manually is a pain.

So I built a lightweight status bar that shows your usage right in your terminal:

`🔋 T:48.0k/133.3k | $:59.28/119 | ⏱️31m | Usage:50%`

**Features:**
- Real-time token & cost tracking
- Color-coded warnings (green → yellow → red)
- Shows time until session reset
- One-line installation (seriously!)

**Install:**
```bash
curl -fsSL https://raw.githubusercontent.com/leeguooooo/claude-code-usage-bar/main/web-install.sh | bash
```

That's it! Just restart Claude Code and you'll see your usage.

![Claude Status Bar](https://raw.githubusercontent.com/leeguooooo/claude-code-usage-bar/main/img.png)

**Technical details:**
- Built on top of the excellent claude-monitor by @Maciek-roboblog
- Available on PyPI: `pip install claude-statusbar`
- Works with tmux, zsh prompts, etc.
- Open source: https://github.com/leeguooooo/claude-code-usage-bar

Would love your feedback! What features would you like to see?

---

## r/programming Post

**Title:** Built a one-line installer that auto-configures AI usage monitoring in your terminal

**Body:**
I was frustrated with not knowing my AI token usage until it was too late, so I built a tool with a focus on zero-friction installation.

**The one-liner does everything:**
```bash
curl -fsSL https://raw.githubusercontent.com/leeguooooo/claude-code-usage-bar/main/web-install.sh | bash
```

This automatically:
1. Detects your package manager (pip/pipx/uv)
2. Installs the package
3. Configures your IDE's status bar
4. Sets up shell aliases
5. Tests everything works

**The result:** Real-time usage in your status bar
`🔋 T:48.0k/133.3k | $:59.28/119 | ⏱️31m | Usage:50%`

**Technical approach:**
- Fallback chain: tries uv → pipx → pip → installs uv if nothing found
- Auto-detects shell (bash/zsh/fish) for aliases
- Modifies IDE settings safely (backs up existing config)
- Pure Python stdlib for core, optional deps for enhanced features

GitHub: https://github.com/leeguooooo/claude-code-usage-bar

Curious what others think about this installation approach. Too magical or just right?