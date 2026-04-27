---
description: Wipe the status-bar config back to defaults
allowed-tools: ["Bash"]
---

# Status Bar — reset

Run:

```bash
cs config reset
```

This deletes `~/.claude/claude-statusbar.json` so every key falls back to its built-in default (style=classic, theme=graphite, density=regular, all `show_*` toggles at their defaults). Idempotent — running it twice is harmless.

Then confirm with `cs config show` and tell the user the original look is restored.
