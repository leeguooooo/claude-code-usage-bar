---
name: claude-statusbar
description: Manage `cs` (claude-statusbar) — switch theme/style/density, override severity colors, preview combinations, run doctor, reset config, install or remove the bar, toggle fast/daemon mode, show cost or prompt-cache age, or toggle the activity segments (todos, active tool, running subagents, session duration, lines changed, git ahead/behind). Use whenever the user mentions cs, claude-statusbar, status bar, status line, 状态栏, 主题, theme switching, style switching, color customization, 余量颜色, 警告颜色, severity color, /statusbar, cs preview, cs doctor, fast mode, daemon, refreshInterval, 5h/7d window, context window display, prompt cache, todos / 待办, active tool, subagents / 子agent, session duration / 时长, lines changed / 行数, git ahead-behind / 领先落后, forecast / 预测 / 还能用多久, at-risk chip, show_forecast, or asks to install / configure / diagnose / customize the bottom status line in Claude Code.
---

# claude-statusbar control skill

Use this skill any time the user wants to inspect, change, customize, or
diagnose the `cs` status bar. Replaces the older individual slash commands
(`/statusbar`, `/statusbar-theme`, `/statusbar-style`, `/statusbar-preview`,
`/statusbar-doctor`, `/statusbar-reset`) — they still work but this skill
covers all of them with conversational intent.

## Decision tree

Match the user's intent to the right `cs` command. Run it via Bash, then
give a short confirmation (one line, no lecture).

| User intent | Command |
|---|---|
| Inspect current config | `cs config show` |
| List themes | `cs themes` |
| List styles | `cs styles` |
| Switch theme to `<name>` | `cs config set theme <name>` |
| Switch style to `<name>` | `cs config set style <name>` |
| Change density | `cs config set density <compact\|regular\|cozy>` |
| Show all 27 combinations | `cs preview` |
| Filter preview to one style/theme | `cs preview --style <s>` or `cs preview --theme <t>` |
| Diagnose problem | `cs doctor` |
| Wipe config | `cs config reset` |
| Install / first-time setup | `cs --setup` |
| Enable fast mode (daemon) | `cs --setup --fast` |
| Disable fast mode | `cs daemon stop` then re-run `cs --setup` |
| Toggle session cost display | `cs config set show_cost true\|false` |
| Toggle prompt-cache countdown | `cs config set show_cache_age true\|false` |
| Toggle project + branch 2nd line | `cs config set show_project_branch true\|false` (default `true`) |
| Toggle todo progress (`▸ task 3/7`, 3rd line) | `cs config set show_todos true\|false` (default `true`) |
| Toggle active-tool indicator `◐` (3rd line) | `cs config set show_tools true\|false` |
| Toggle completed-tool rollup `✓ name×N` (3rd line) | `cs config set show_tool_rollup true\|false` (default off — volume tally) |
| Toggle running-subagent bottom line(s) | `cs config set show_agents true\|false` (default off — Claude Code shows background agents natively) |
| Toggle session duration `⏱` (on identity line) | `cs config set show_duration true\|false` |
| Toggle lines added/removed `+/-` (on identity line) | `cs config set show_lines true\|false` |
| Toggle git ahead/behind `↑↓` (on identity line) | `cs config set show_ahead_behind true\|false` |
| Toggle the `bar_shimmer` twinkling starfield (experimental, classic only) | `cs config set bar_shimmer true\|false` (default off) |
| Toggle the rate-limit forecast (→NN% projected use / ⚠eta warning) | `cs config set show_forecast true\|false` (default on) |
| Toggle the faint version + update hint at the identity-line end (`· vX.Y.Z ↑new`) | `cs config set show_version true\|false` (default on) |
| Toggle the ⚙ session-mode line (effort/thinking/fast/output-style) | `cs config set show_mode true\|false` (default on) |
| Toggle the per-effort colour gradient on the mode line | `cs config set mode_gradient true\|false` (default on) |
| Hide weekly bar | `cs config set show_weekly false` |
| Set warning threshold | `cs config set warning_threshold <0-100>` |
| Set critical threshold | `cs config set critical_threshold <0-100>` |
| Auto-collapse to hairline below width | `cs config set auto_compact_width <px>` |
| Force / disable no-quota (API) mode | `cs config set api_mode <auto\|on\|off>` |

## No-quota mode (third-party relay / Bedrock / Vertex)

When Claude Code points at a third-party relay (`ANTHROPIC_BASE_URL` ≠
`api.anthropic.com`) or a cloud backend (`CLAUDE_CODE_USE_BEDROCK` /
`CLAUDE_CODE_USE_VERTEX`), the official 5h/7d quota doesn't exist. cs detects
this and switches to a **no-quota layout**: the two quota battery bars are
dropped and the **context window is promoted to its own `ctx[…]` battery bar**
(green→yellow→red on 70/85% used), followed by the model name + the usual
live-activity tail. This mirrors claude-hud's behavior and is what to reach for
when a user says "用 API 就没状态了 / 连上下文都没了".

- Detection is automatic (`api_mode = auto`, the default). A transcript-based
  heuristic also catches relays whose env var didn't reach the statusLine
  subprocess (an assistant turn exists yet quota never arrived → no-quota).
- Force it on a setup where auto-detect misses: `cs config set api_mode on`
  (or per-shell `CS_API_MODE=on`). Force the official layout back with
  `api_mode off`. `CS_API_MODE` env wins over the saved config.
- Works under both the inline and fast-mode (daemon) render paths.

## Per-severity color overrides (v3.4.1+)

The user can override the three severity colors independently of theme:

```bash
cs config set color_ok   "#4ec85b"   # calm / safe
cs config set color_warn "#e8b260"   # warning
cs config set color_hot  "#e87474"   # critical

cs config set color_ok ""            # clear back to theme default
```

Accepts `#rrggbb`, `#rgb`, or bare `rrggbb`. The override layers on top of
whatever theme is active — no need to switch theme just to tune one color.

**When user says** "make 余量颜色 / safe color / green sharper", "warning
偏淡", "critical too red" — go to the override, not the theme.

## Vibe → theme suggestion

If the user describes a vibe instead of naming a theme, suggest one and
ask before switching:

| Vibe / context | Theme |
|---|---|
| Muted, professional, dark terminal | `graphite` (default) |
| Soft, warm, dark | `twilight` |
| Classic dev / Nord-inspired | `nord` |
| High contrast, vivid | `dracula` |
| Warm, cute, light bg | `sakura` |
| Light terminal | `linen` |
| Pure grayscale / no color | `mono` |
| Popular pastel, easy on long viewing | `catppuccin-mocha` |
| Deeper neon-blue mood | `tokyo-night` |

## Render anatomy (so you can explain what you're changing)

```
5h[██16% ░░░]⏰2h27m | 7d[██32%  ░░]⏰4d05h | Opus 4.7(280k/1M) | $ 1.42 | cache 4m23s
└─ 5h ─────┘└──5h──┘  └─ 7d ──┘ └─7d─┘   └────context───────┘  └cost┘  └─cache─┘
```

Every numeric segment colors itself by its own severity (since v3.4):
- 5h → `theme.s_*` chosen from `msgs_pct`
- 7d → `theme.s_*` chosen from `weekly_pct`
- model+context → `theme.s_*` chosen from `ctx_used_pct` (None → neutral)
- cache → its own string-age severity (COLD → red, <1m → yellow, else green)
- `[ ]`, `( )`, ` | ` → `theme.mute` (recede behind data)

## Common diagnostic flows

**"Status bar isn't showing"** → `cs doctor`. It self-checks:
- Claude Code's `~/.claude/settings.json` has the `statusLine` block
- the `cs` binary is on PATH
- whether the daemon is alive (if fast-mode configured)
- whether the cache files are stale

**"refreshInterval too high"** → `cs doctor` will recommend `cs --setup --fast`
when it sees `refreshInterval ≤ 2s` on the inline command. Fast mode drops
1Hz CPU from ~6% to ~2%.

**"Color won't change after `cs config set theme X`"** → check the user
isn't on a Claude Code session that read `settings.json` at start. Ask
them to send a new prompt; the next render picks up the new theme.

## Don't

- Don't lecture about ANSI codes or terminal compatibility unless asked.
- Don't suggest editing `~/.claude/claude-statusbar.json` by hand. Use
  `cs config set <key> <value>`.
- Don't change theme just to fix one color — use `color_ok / color_warn /
  color_hot` overrides.
- Don't run destructive commands (`cs config reset`, `cs daemon stop`)
  without confirming with the user.

## Style of response

Be terse. Run the command, paste the one-line confirmation, point at the
next step if relevant. The status bar is on screen — they can see the
result immediately, no need to describe it.
