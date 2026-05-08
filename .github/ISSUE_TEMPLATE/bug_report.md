---
name: Bug report
about: Something is rendering wrong, the bar isn't showing, or `cs` is misbehaving.
title: ''
labels: bug
assignees: ''
---

## What's wrong

Brief description of the bug. What did you expect, what did you see?

## Reproduction

If you can:
- A specific theme / style combination that triggers it
- The exact `cs config show` output
- The terminal emulator + version (iTerm2 / Terminal.app / Alacritty / Ghostty / ...)
- Whether you're on inline or daemon mode (`cs --setup --fast`)

## `cs doctor` output

`cs doctor` self-checks settings, daemon state, and cache health. Paste its output here:

```
$ cs doctor
[paste output]
```

## Versions

- `cs --version`:
- macOS / Linux + version:
- Claude Code version:
- Python version (`python3 --version`):

## Anything else

Stack traces, screenshots, repro stdin payload from `~/.cache/claude-statusbar/last_stdin.json` if relevant.
