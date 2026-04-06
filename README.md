# Claude Status Bar

Lightweight Claude Code status bar monitor for the built-in `statusLine` hook.

It shows your current Claude.ai rate-limit usage, reset timers, context window usage, and an optional ASCII pet in a compact single-line format.

## What it shows

```
5h[███38%░░░░]⏰2h14m | 7d[███87%███░]⏰3d05h | Opus 4.6(90.0k/1.0M) | ᓚᘏᗢ Giga:working!
```

| Segment | Meaning |
|---------|---------|
| `5h[███38%░░░░]` | 5-hour rate-limit usage |
| `⏰2h14m` | Time until the 5-hour window resets |
| `7d[███87%███░]` | 7-day rate-limit usage |
| `⏰3d05h` | Time until the 7-day window resets |
| `Opus 4.6(90.0k/1.0M)` | Model name plus current context usage |
| `ᓚᘏᗢ Giga:working!` | Optional status-bar pet |

Colors default to green / yellow / red at `30%` and `70%`, and can be customized.

## Install

### One-line install (recommended)

```bash
curl -fsSL "https://raw.githubusercontent.com/leeguooooo/claude-code-usage-bar/main/web-install.sh?v=$(date +%s)" | bash
```

This installs the package, configures Claude Code statusLine, and sets up aliases. Restart Claude Code to see it.

### Package managers

```bash
pip install claude-statusbar     # pip
uv tool install claude-statusbar # uv
pipx install claude-statusbar    # pipx
```

Then add to `~/.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "cs"
  }
}
```

## Usage

```bash
cs                  # show status bar (shortest alias)
cs --json-output    # machine-readable JSON
cs --no-color       # disable ANSI colors
cs --hide-pet       # hide the ASCII pet
cs --warning-threshold 40 --critical-threshold 85
cs --no-auto-update # disable auto-update checks
```

`--plan` still exists for older scripts, but it is deprecated and no longer changes the status line output.

### Environment variables

| Variable | Effect |
|----------|--------|
| `CLAUDE_STATUSBAR_NO_UPDATE=1` | Disable automatic update checks |
| `CLAUDE_STATUSBAR_HIDE_PET=1` | Hide the status bar pet |
| `CLAUDE_STATUSBAR_WARNING_THRESHOLD=40` | Switch from green to yellow at 40% |
| `CLAUDE_STATUSBAR_CRITICAL_THRESHOLD=85` | Switch from yellow to red at 85% |
| `NO_COLOR=1` | Disable ANSI colors |

`CLAUDE_PLAN` is still accepted for legacy compatibility, but it no longer changes the rendered status line.

### JSON output

Use `--json-output` if you want a machine-readable payload instead of the formatted status line:

```bash
cs --json-output
```

## Data source

Rate-limit data comes directly from **Anthropic's official API headers** exposed to Claude Code status-line commands through stdin.

Context-window usage comes from the same stdin payload that Claude Code sends to custom `statusLine` commands.

Requires Claude Code `v2.1.80+`.

## Upgrading

Auto-updates once per day. To upgrade manually:

```bash
pip install --upgrade claude-statusbar
```

To disable auto-updates: `export CLAUDE_STATUSBAR_NO_UPDATE=1`

## License

MIT

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=leeguooooo/claude-code-usage-bar&type=Date)](https://star-history.com/#leeguooooo/claude-code-usage-bar&Date)
