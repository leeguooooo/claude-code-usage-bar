# Claude Status Bar

Lightweight Claude Code status bar monitor — see your rate limits, context window, and promo status at a glance.

![Claude Code Status Bar](https://raw.githubusercontent.com/leeguooooo/claude-code-usage-bar/main/img.png)

## What it shows

```
[███████░░░] 5h 68% | [█░░░░░░░░░] 7d 5% | ⏰0h21m | max5 🔥x2[03:00~21:00] | Opus 4.6(13.4k/1.0M)
```

| Segment | Meaning |
|---------|---------|
| `5h 68%` | 5-hour rate limit usage (official Anthropic data) |
| `7d 5%` | 7-day rate limit usage (official Anthropic data) |
| `⏰0h21m` | Time until 5h window resets |
| `max5` | Your plan tier |
| `🔥x2[03:00~21:00]` | 2x promo active, showing local time window |
| `Opus 4.6(13.4k/1.0M)` | Model + context window usage (used/total) |

Colors: green (<30%) | yellow (30-70%) | red (>70%)

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
cs --plan max5      # set your plan (pro / max5 / max20)
cs --no-color       # disable ANSI colors
cs --no-auto-update # disable auto-update checks
```

### Plan tiers

Set once, saved automatically:

```bash
cs --plan pro     # Pro $20/mo
cs --plan max5    # Max $100/mo
cs --plan max20   # Max $200/mo
```

### Environment variables

| Variable | Effect |
|----------|--------|
| `CLAUDE_STATUSBAR_NO_UPDATE=1` | Disable automatic update checks |
| `CLAUDE_PLAN=max5` | Set plan tier |
| `NO_COLOR=1` | Disable ANSI colors |

## 2x Promo Time Window

During Anthropic's 2x usage promotion, the status bar shows the bonus window in your **local timezone**:

| Time | Status |
|------|--------|
| Weekday off-peak | `🔥x2[03:00~21:00]` (example in JST) |
| Weekday peak | `1x[21:00~03:00]` |
| Weekend | `🔥x2[all day]` |
| Promo expired | *(hidden)* |

Peak hours: 8AM-2PM ET (weekdays only). Weekends are always 2x.

## Data source

All rate limit data comes directly from **Anthropic's official API headers** via Claude Code's statusLine stdin injection (requires Claude Code >= v2.1.80). No estimation or guessing.

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
