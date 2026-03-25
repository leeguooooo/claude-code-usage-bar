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
[████████░░] msgs 82% | [████░░░░░░] tkns 42% | ⏰2h51m | Opus 4.6
```

### Progress Bar Spec

- Width: 10 characters (`█` filled, `░` empty)
- Two independent dimensions: messages and tokens
- Each bar colored independently based on its own percentage
- Rounding: `round()`, but always show at least 1 filled block when >0%

### Color Thresholds

| Level | Condition | Color | Meaning |
|-------|-----------|-------|---------|
| Safe | <30% | Green (`\033[32m`) | No action needed |
| Warning | 30%-70% | Yellow (`\033[33m`) | Stay aware |
| Critical | >70% | Red (`\033[31m`) | Consider switching model |

- Each progress bar's filled portion (`█`) is colored by its own percentage
- Surrounding text (separators `|`, timer, model name) uses the highest severity of the two dimensions

### Extreme Cases

- Over 100%: `[██████████] msgs 100%+` — full red bar, text shows `100%+`
- Data unavailable: `[░░░░░░░░░░] msgs --% | ...` (empty bar with dimmed fill)
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
Critical: [████████░░] msgs 82% | [████░░░░░░] tkns 42% | ⏰1h15m | Opus 4.6
Near RST: [█████████░] msgs 92% | [█████░░░░░] tkns 48% | ⏰0h08m | Opus 4.6
Bypass:   [████████░░] msgs 82% | [████░░░░░░] tkns 42% | ⏰1h15m | Opus 4.6 | ⚠️BYPASS
Over:     [██████████] msgs 100%+ | [██████████] tkns 100%+ | ⏰0h03m | Opus 4.6
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

### Fallback when claude-monitor is unavailable

If claude-monitor is not installed, fall back to `direct_data_analysis()` which reads JSONL files directly. This path counts entries as messages and uses heuristic limits. The progress bars will still render but limits may be less accurate.

### Cache Mechanism

File: `~/.cache/claude-statusbar/cache.json` (portable, per-user)

```json
{
  "timestamp": "2026-03-25T05:00:00Z",
  "messages_count": 204,
  "message_limit": 250,
  "total_tokens": 38600,
  "token_limit": 88000,
  "reset_time_utc": "2026-03-25T09:00:00Z",
  "models": ["claude-sonnet-4-6"],
  "source": "original"
}
```

Read/write strategy:
1. Cache age <30s → use cache, skip claude-monitor (fast path)
2. Cache age >30s → use stale cache for display, fork background refresh (non-blocking)
3. Cache missing → synchronous claude-monitor call (cold start)

Atomic writes: background refresh writes to a temp file then `os.rename()` to prevent partial reads.

30s chosen because statusline refreshes roughly per-interaction.

### Plan detection

The `--plan` flag is retained for explicit override. Without it:
1. If claude-monitor P90 calculation has enough data (>=5 blocks), use dynamic limits
2. Otherwise fall back to `custom` preset (44k tokens, 250 messages)

Users are encouraged to set `--plan max5|max20` for accurate limits matching their subscription tier.

> Note: claude-monitor plan names (`max5`, `max20`) reflect the legacy naming. `max5` ≈ Max $100/month, `max20` ≈ Max $200/month in the current Anthropic pricing. This mapping may need updating as Anthropic changes plan names.

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
| `🔋:36k/88k` | `[████░░░░░░] tkns 42%` |
| `⌛️:2h 51m` | `⏰2h51m` (no space, save width) |
| `🤖:Opus 4.6` | `Opus 4.6` |
| `⚠️BYPASS` | `⚠️BYPASS` (unchanged) |

## JSON Output

`--json-output` continues to emit all available data (including cost, context window, etc.) for programmatic consumers. Only the human-readable status bar format changes.

## Plan Presets (synced with claude-monitor v3.1.0)

| Plan | Token Limit | Message Limit | Notes |
|------|-------------|---------------|-------|
| pro | 19,000 | 250 | Pro plan |
| max5 | 88,000 | 1,000 | ≈ Max $100/month |
| max20 | 220,000 | 2,000 | ≈ Max $200/month |
| custom | 44,000 | 250 | P90 dynamic fallback |

Cost limits are retained in code for `--json-output` but excluded from the status bar display.

## ANSI Color Support

Claude Code's terminal renderer supports ANSI escape codes in statusline output. A `--no-color` flag is available for environments that do not (e.g., piping to a file).
