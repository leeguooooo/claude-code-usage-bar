---
description: Switch the status-bar color theme (graphite / twilight / linen)
argument-hint: <graphite|twilight|linen>
allowed-tools: ["Bash"]
---

# Status Bar — set theme

Argument: `$ARGUMENTS`

Steps:

1. If `$ARGUMENTS` is empty, run `cs themes` to list options and ask the user to pick.
2. Otherwise, run:
   ```bash
   cs config set theme $ARGUMENTS
   ```
3. Show an immediate preview using cached data:
   ```bash
   cat ~/.cache/claude-statusbar/last_stdin.json | cs --theme $ARGUMENTS
   ```
   If the cache file does not exist, skip this step.
4. Tell the user the change is persistent.

If `$ARGUMENTS` is not one of `graphite`, `twilight`, `linen`, surface the error and suggest `cs themes`.
