---
description: Show current status-bar config and list available styles + themes
allowed-tools: ["Bash"]
---

# Status Bar — overview

Run these three commands and present the output to the user, then briefly tell them how to switch:

```bash
cs config show
cs styles
cs themes
```

Then point out:

- Switch persistent style:  `cs config set style <name>` (or via `/statusbar-style <name>`)
- Switch persistent theme:  `cs config set theme <name>` (or via `/statusbar-theme <name>`)
- See every combination side-by-side: `/statusbar-preview`
- Show this session's $ cost on the bar: `cs config set show_cost true`
- One-shot trial without saving: `cs --style capsule --theme twilight`
- Wipe everything back to defaults: `/statusbar-reset`
- Diagnose problems (paste in any bug report): `/statusbar-doctor`

Keep the response short. Don't lecture about ANSI colors or terminal compatibility.
