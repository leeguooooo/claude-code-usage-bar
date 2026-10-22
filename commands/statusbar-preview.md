---
description: Render the three status-bar looks using your real cached data
allowed-tools: ["Bash"]
---

# Status Bar — preview the looks

Run:

```bash
cs preview
```

This renders the three looks — aurora with ■ blocks (default), aurora with a thin ━ line, and classic — with the user's real numbers from `~/.cache/claude-statusbar/last_stdin.json`.

After running it, ask the user which look they want and offer to switch with `/statusbar-style block|thin|classic`. Do not pick for them.
