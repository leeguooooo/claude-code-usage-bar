---
description: Switch the status-bar look (aurora blocks / aurora thin / classic)
argument-hint: <block|thin|classic>
allowed-tools: ["Bash"]
---

# Status Bar — set look

Argument: `$ARGUMENTS`

There are three looks:

| Look | Commands |
|---|---|
| `block` — aurora with ■ bars (default) | `cs config set style aurora && cs config set bar_glyph block` |
| `thin` — aurora with a thin ━ line | `cs config set style aurora && cs config set bar_glyph thin` |
| `classic` — the original battery bar | `cs config set style classic` |

Steps:

1. If `$ARGUMENTS` is empty, run `cs preview` to show all three and ask the user to pick.
2. Otherwise run the commands for that look from the table above.
3. Render a one-line preview from cached real data so the user sees the result:
   ```bash
   cat ~/.cache/claude-statusbar/last_stdin.json | cs
   ```
   If the cache file does not exist, skip this step — no Claude Code session has populated it yet.
4. Tell the user the change is persistent for all future Claude Code sessions.

If `$ARGUMENTS` is not `block`, `thin` or `classic`, list the three looks and ask which one they meant.
