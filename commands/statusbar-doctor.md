---
description: Run cs doctor to diagnose why the status bar isn't showing what you expect
allowed-tools: ["Bash"]
---

# Status Bar — doctor

Run:

```bash
cs doctor
```

The output covers:

- Whether `cs` is on PATH and where it resolves to
- Version + Python interpreter
- Whether `~/.claude/settings.json` has our statusLine entry (and whether something else is occupying it)
- Last `last_stdin.json` cache age (i.e. is Claude Code actually pushing data)
- Terminal size and `TERM`
- Current resolved `style` / `theme` / `show_*` toggles
- Number of `/statusbar*` slash commands installed

Show the user the full output as-is. If anything is flagged with `✗`, point at that line specifically and propose the obvious next step (`cs --setup` to create the statusLine entry, `cs upgrade` to upgrade — never a raw pip/uv command, `cs upgrade` picks the channel the install actually uses, etc.). Don't editorialize beyond what the output already says.
