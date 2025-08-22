# Demo Walkthrough for Claude Status Bar

## 🎬 Quick Demo Script

### 1. Show the Problem
```bash
# Open Claude Code
# Show token usage is not visible
# Mention: "I never know how many tokens I've used until it's too late"
```

### 2. One-Line Installation
```bash
# Show terminal
$ curl -fsSL https://raw.githubusercontent.com/leeguooooo/claude-code-usage-bar/main/web-install.sh | bash

# Output shows:
✅ Installing claude-statusbar...
✅ Configuring Claude Code status bar...
✅ Setting up shell aliases...
✅ Installation complete!
```

### 3. Restart Claude Code
```bash
# Close and reopen Claude Code
# The status bar now shows at the bottom
```

### 4. Live Usage Demo
```bash
# Type a message in Claude Code
# Watch the status bar update in real-time:

🔋 T:12.3k/133.3k | $:15.28/119 | ⏱️2h31m | Usage:9% 🟢

# Send another message
# Watch it increase:

🔋 T:24.5k/133.3k | $:30.56/119 | ⏱️2h29m | Usage:18% 🟢

# Show color changes as usage increases
```

### 5. Terminal Integration
```bash
# Show it works in terminal too
$ claude-statusbar
🔋 T:24.5k/133.3k | $:30.56/119 | ⏱️2h29m | Usage:18% 🟢

# Show the short alias
$ cs
🔋 T:24.5k/133.3k | $:30.56/119 | ⏱️2h29m | Usage:18% 🟢

# Show tmux integration
# Add to .tmux.conf:
set -g status-right '#(claude-statusbar)'
```

## 📸 Key Screenshots Needed

1. **Before**: Claude Code without status bar
2. **Installation**: Terminal showing the one-line install command
3. **After**: Claude Code with the status bar showing usage
4. **Terminal**: Running `cs` command in terminal
5. **Tmux**: Status bar integrated in tmux

## 🎥 GIF Recording Tips

Use **Kap** (Mac) or **Peek** (Linux) to record:

1. Keep it under 10 seconds
2. Show the most impactful moment (installation → working)
3. Use high contrast terminal theme
4. Zoom in on the status bar area
5. Loop the GIF

## 📝 Script for Video Demo

**[0-3s]** "Tired of running out of Claude tokens?"
*Show Claude Code without monitoring*

**[3-6s]** "Install with one command"
*Show: curl -fsSL ... | bash*

**[6-9s]** "See your usage in real-time"
*Show status bar updating as you type*

**[9-12s]** "Never get caught off guard again"
*Show color-coded warnings*