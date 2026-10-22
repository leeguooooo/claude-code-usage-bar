---
description: Show current status-bar config and the available looks
allowed-tools: ["Bash"]
---

# Status Bar — overview

Run these two commands and present the output to the user, then briefly tell them how to switch:

```bash
cs config show
cs styles
```

Then point out:

- Switch look: `/statusbar-style block|thin|classic`
- See all three side-by-side: `/statusbar-preview`
- Show this session's $ cost on the bar: `cs config set show_cost true`
- One-shot trial without saving: `cs --style classic`
- Wipe everything back to defaults: `/statusbar-reset`
- Diagnose problems (paste in any bug report): `/statusbar-doctor`

Keep the response short. Don't lecture about ANSI colors or terminal compatibility.
