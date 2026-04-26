---
description: Switch the status-bar style (classic / capsule / hairline)
argument-hint: <classic|capsule|hairline>
allowed-tools: ["Bash"]
---

# Status Bar — set style

Argument: `$ARGUMENTS`

Steps:

1. If `$ARGUMENTS` is empty, run `cs styles` to list options and ask the user to pick.
2. Otherwise, run:
   ```bash
   cs config set style $ARGUMENTS
   ```
3. After the change, render a one-line preview using cached real data so the user sees the result immediately:
   ```bash
   cat ~/.cache/claude-statusbar/last_stdin.json | cs --style $ARGUMENTS
   ```
   If the cache file does not exist, skip this step — it just means no Claude Code session has populated it yet.
4. Tell the user the change is now persistent for all future Claude Code sessions.

If `$ARGUMENTS` is not one of `classic`, `capsule`, `hairline`, surface the error from `cs` directly and suggest `cs styles` for valid options.
