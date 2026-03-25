# Rate-Limit Focused Status Bar Redesign

## Problem

Current status bar displays data that is irrelevant to the target audience (Max $100/$200 subscribers):
- `cost` is meaningless for subscription users
- `context window %` and `lines changed` are noise for rate-limit awareness
- The most critical signal — "how close am I to being rate-limited?" — is buried among other metrics

Target users want one thing: **know when to switch to a cheaper model before getting throttled**.

## Target Users

- Claude Max $100/month and Max $200/month subscribers
- Using Claude Code via claude.ai login (not API key)
- International audience (English-only UI)

## Design

### Output Format

Dual progress bar with reset countdown and model indicator:

```
[████████░░] msgs 82% | [██░░░░░░░░] tkns 36% | ⏰2h51m | Opus 4.6
```

### Progress Bar Spec

- Width: 10 characters (`█` filled, `░` empty)
- Two independent dimensions: messages and tokens
- Each bar colored independently based on its own percentage

### Color Thresholds

| Level | Condition | Color | Meaning |
|-------|-----------|-------|---------|
| Safe | <30% | Green (`\033[32m`) | No action needed |
| Warning | 30%-70% | Yellow (`\033[33m`) | Stay aware |
| Critical | >70% | Red (`\033[31m`) | Consider switching model |

- Each progress bar is colored independently
- Overall line color follows the highest severity of the two dimensions

### Extreme Cases

- Over 100%: `[██████████] msgs 100%+` — display `100%+`, full red bar
- Data unavailable: `[??????????] msgs --% | ...`
- Reset <10min: timer shown normally, no special color change

### Bypass Permissions

Appended at end when detected: `| ⚠️BYPASS`

Detection sources:
1. `CLAUDE_SKIP_PERMISSIONS=1` env var
2. `settings.json` `defaultMode == "bypassPermissions"`

### Full Examples

```
Safe:     [███░░░░░░░] msgs 28% | [█░░░░░░░░░] tkns 12% | ⏰4h02m | Opus 4.6
Warning:  [██████░░░░] msgs 55% | [██░░░░░░░░] tkns 20% | ⏰2h51m | Opus 4.6
Critical: [████████░░] msgs 82% | [████░░░░░░] tkns 36% | ⏰1h15m | Opus 4.6
Near RST: [█████████░] msgs 92% | [█████░░░░░] tkns 48% | ⏰0h08m | Opus 4.6
Bypass:   [████████░░] msgs 82% | [████░░░░░░] tkns 36% | ⏰1h15m | Opus 4.6 | ⚠️BYPASS
```

## Data Sources

### Two execution modes

| Mode | Trigger | Data Source |
|------|---------|-------------|
| statusLine | Claude Code calls `cs` with stdin | stdin (model) + claude-monitor via cache (msgs, tokens, reset) |
| standalone | User runs `cs` directly | claude-monitor directly (all fields) |

### Why claude-monitor is required

Claude Code stdin does **not** provide:
- `rate_limits` — missing even for Max subscribers (confirmed v2.1.74/2.1.77)
- Message count / message limit
- Reset time

claude-monitor reads `~/.claude/projects/**/*.jsonl` and calculates all of these.

### Cache Mechanism

File: `/tmp/claude-statusbar-cache.json`

```json
{
  "timestamp": "2026-03-25T05:00:00Z",
  "messages_count": 204,
  "message_limit": 250,
  "total_tokens": 38600,
  "token_limit": 19000,
  "reset_time_utc": "2026-03-25T09:00:00Z",
  "models": ["claude-sonnet-4-6"],
  "source": "original"
}
```

Read/write strategy:
1. Cache age <30s → use cache, skip claude-monitor (fast path)
2. Cache age >30s → use stale cache for display, fork background refresh (non-blocking)
3. Cache missing → synchronous claude-monitor call (cold start)

30s chosen because statusline refreshes roughly per-interaction.

## Fields Removed

| Field | Reason |
|-------|--------|
| `💰 cost` | Meaningless for subscription users |
| `📝 lines changed` | Unrelated to rate-limit awareness |
| `🧠 context window %` | Useful but not core; space-constrained |

## Fields Retained (transformed)

| Old | New |
|-----|-----|
| `📨:204/250` | `[████████░░] msgs 82%` |
| `🔋:38.6k/19k` | `[██░░░░░░░░] tkns 36%` |
| `⌛️:2h51m` | `⏰2h51m` |
| `🤖:Opus 4.6` | `Opus 4.6` |
| `⚠️BYPASS` | `⚠️BYPASS` (unchanged) |

## JSON Output

`--json-output` continues to emit all available data (including cost, context window, etc.) for programmatic consumers. Only the human-readable status bar format changes.

## Plan Presets (synced with claude-monitor v3.1.0)

| Plan | Token Limit | Cost Limit | Message Limit |
|------|-------------|------------|---------------|
| pro | 19,000 | $18 | 250 |
| max5 | 88,000 | $35 | 1,000 |
| max20 | 220,000 | $140 | 2,000 |
| custom | 44,000 | $50 | 250 |
