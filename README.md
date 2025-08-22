# Claude Status Bar Monitor

A lightweight status bar monitor for Claude AI token usage. This tool displays real-time usage statistics in your terminal status bar.

## Features

- 🔋 Real-time token usage tracking
- 💰 Cost monitoring
- ⏱️ Session reset timer
- 🎨 Color-coded usage indicators (green/yellow/red)
- 📊 Automatic P90 limit detection
- 🚀 Lightweight and fast
- 📦 Available as PyPI package
- 🔧 One-line web installation

## Quick Installation

### 🚀 One-Line Web Install (Easiest)

```bash
curl -fsSL https://raw.githubusercontent.com/leeguooooo/claude-code-usage-bar/main/web-install.sh | bash
```

Or with wget:
```bash
wget -qO- https://raw.githubusercontent.com/leeguooooo/claude-code-usage-bar/main/web-install.sh | bash
```

### 📦 Install from PyPI

```bash
# Using uv (recommended - fastest)
uv tool install claude-statusbar

# Or using pip
pip install claude-statusbar

# Or using pipx (isolated environment)
pipx install claude-statusbar
```

After installation, run from anywhere:
```bash
claude-statusbar  # Full command
cstatus          # Short alias
cs               # Shortest alias
```

### 🔨 Install from Source

```bash
# Clone and install
git clone https://github.com/leeguooooo/claude-code-usage-bar.git
cd claude-code-usage-bar
pip install -e .

# Or use the local installer
./install.sh
```

## Usage

### Basic Usage

Run the script directly:
```bash
./statusbar.py
```

Output example:
```
🔋 T:15.2k/88k | $:12.50/35 | ⏛2h 35m | Usage:17%
```

### Integration with tmux

Add to your `~/.tmux.conf`:
```bash
set -g status-right '#(~/path/to/claude-statusbar-monitor/statusbar.py)'
set -g status-interval 10
```

### Integration with Zsh (Oh My Zsh)

Add to your `~/.zshrc`:
```bash
# Claude usage in prompt
claude_usage() {
    ~/path/to/claude-statusbar-monitor/statusbar.py
}
RPROMPT='$(claude_usage)'
```

### Integration with i3 status bar

Add to your i3 config:
```bash
bar {
    status_command while :; do echo "$(~/path/to/claude-statusbar-monitor/statusbar.py)"; sleep 10; done
}
```

## How It Works

The monitor has two data sources:

1. **Primary**: Uses the installed `claude-monitor` package for accurate P90 analysis
2. **Fallback**: Direct file analysis if the package is not available

## Status Indicators

- **T**: Token usage (current/limit)
- **$**: Cost in USD (current/limit)
- **⏱️**: Time until session reset
- **Usage %**: Color-coded percentage
  - 🟢 Green: < 30%
  - 🟡 Yellow: 30-70%
  - 🔴 Red: > 70%

## Troubleshooting

### No data showing

1. Make sure `claude-monitor` is installed:
```bash
pip install claude-monitor
```

2. Check if Claude has active sessions:
```bash
claude-monitor --plan custom
```

3. Verify the script has execution permissions:
```bash
chmod +x statusbar.py
```

### Wrong timezone

The monitor automatically detects your timezone. If incorrect, set it manually in your environment:
```bash
export TZ='America/New_York'
```

## Uninstallation

To remove the status bar monitor and clean up aliases:

```bash
./uninstall.sh
```

This will:
- Remove shell aliases from your configuration files
- Optionally uninstall the claude-monitor package
- Keep the project files (you can delete them manually if needed)

## License

MIT

## Credits

Built on top of [Claude Code Usage Monitor](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor) by [@Maciek-roboblog](https://github.com/Maciek-roboblog)