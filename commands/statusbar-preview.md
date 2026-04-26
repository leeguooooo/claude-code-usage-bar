---
description: Render every style × theme combination using your real cached data
allowed-tools: ["Bash"]
---

# Status Bar — preview all combinations

Run:

```bash
cs preview
```

This renders all 9 combinations (3 styles × 3 themes) with the user's real numbers from `~/.cache/claude-statusbar/last_stdin.json`.

After running it, ask the user which combination they want and offer to switch with `cs config set style <name>` and `cs config set theme <name>`. Do not pick for them.
