# What the status bar shows

Full reference for every segment `cs` can render. Most are on by default; the
opt-in ones are noted. Toggle any of them from the [configuration
reference](configuration.md) or `cs config set <key> <value>`.

```
5h[   27%    ]⏰1h28m →42% | 7d[   79%    ]⏰11h28m →88% | Opus 4.8(350.0k/1.0M) | cache 4m23s | $ 1.42
⤷ claude-code-usage-bar ⎇ main● · +182 -47 · ⏱ 12m · v3.12.0
⚙ effort:high · think:on · fast:off · style:default
```

| Segment | Meaning |
|---------|---------|
| `5h[27%]` | 5-hour rate-limit usage (rolling window from Anthropic API headers) |
| `⟳ 5h/7d stale·restart` | Shown (in place of the two bars) when the cached 5h/7d data has gone stale because cs stopped receiving fresh ticks — usually another tool displaced the statusLine, or the daemon died. Restart Claude Code to refresh; if it keeps happening, run `cs --setup` to reclaim the statusLine. `cs doctor` explains it in detail. |
| `⏰1h28m` | Time until the 5-hour window resets |
| `7d[79%]` | 7-day rate-limit usage |
| `⏰11h28m` | Time until the 7-day window resets |
| `→42%` / `→88%` | Projected end-of-window usage at your current rhythm (`show_projection`, on by default). Muted < 80%, yellow ≥ 80%, red ≥ 100%. The 5h model blends recent pace + whole-window average + a local baseline; the 7d model integrates learned day/night/weekend buckets so a busy first day isn't extrapolated across the week. |
| `⚠~18m` | At-risk warning chip — only when a window is projected to hit 100% **and** the cap is imminent (≤ 1 h). Separate from the projection (`show_forecast`, on by default). |
| `Opus 4.8(350.0k/1.0M)` | Model name + current context window usage |
| `cache 4m23s` / `cache COLD` | Countdown to prompt-cache expiry — the TTL (5min vs 1h) is auto-detected from the transcript, so it's right on a subscription (1h) or an API key (5min). Green when comfortable, yellow under 1min, red on COLD. Cache hits consume ~10× less rate-limit quota — for subscribers, letting it go COLD eats your 5h / 7d windows ~10× faster. Enabled by default; disable with `cs config set show_cache_age false`. See [How the cache countdown works](cache-countdown.md). |
| `$ 1.42` | Session cost in USD as Claude Code reports it. For Pro/Max subscribers this is the **API-equivalent value** of your usage (i.e. what it would cost on the API), not money owed. Useful as an ROI signal. Opt-in: `cs config set show_cost true` |
| `bal[████ 52%] $26.00` | **Relay account balance** — only in no-quota mode (third-party relay / API key). Auto-detected: a background probe queries the relay's OpenAI-compatible billing endpoint (`/dashboard/billing/subscription` + `/usage`, the new-api / one-api de-facto standard) using your key, computes `hard_limit − used`, and caches it 5 min. Renders as a **fuel-gauge battery** (fill = remaining; green full → yellow ≤25% → red ≤10%) with the remaining amount trailing; falls back to plain `bal $809.97` when the relay reports no usable limit. **Shown when the relay exposes that endpoint, silently hidden when it doesn't** — zero config. `cs config set balance_bar false` for plain text; `cs config set show_balance false` to disable entirely. |
| `⤷ <project> ⎇ <branch>●↑2↓1 · +182 -47 · ⏱ 12m` | Second-line identity + session line. Project comes from Claude Code's `workspace.repo.name` (cwd-basename fallback); branch reads `.git/HEAD` directly; the `●` dirty marker is refreshed by a background helper, cached 5 s. Enabled by default — turn off with `cs config set show_project_branch false`. `+added -removed` session lines (`show_lines`, +green/−red) also show by default. Opt-in extras live here too: `↑2↓1` commits ahead/behind upstream (`show_ahead_behind`, reuses the dirty-state `git status` — no extra spawn) and session `⏱` duration (`show_duration`). |
| `▸ <task> (3/7) · ◐ Edit auth.py · ✓ Read×3` | Third "activity" line — what's happening *right now*, parsed from the transcript: the in-progress **todo** + done/total (`show_todos`, on by default), the **active tool** (`◐`, `show_tools`), and an optional completed-tool rollup (`✓ name×N`, `show_tool_rollup`, default off). Omitted entirely when nothing is active. |
| `◐ explore[haiku] <task> 2m15s` | Bottom line(s) — one per running **subagent** (`show_agents`, opt-in, default **off**). Note: Claude Code already shows background agents in its own native panel, so this largely duplicates that; off by default for that reason. |
| `⚙ effort:high · think:on · fast:off · style:default` | **Session-mode line** (`show_mode`, on by default) — how this turn is configured, from stdin. Tinted with a per-effort static gradient (`mode_gradient`) so the level reads at a glance. |
| `#agentparty · ⬡ xdream-agent · ◉ serving · 3 unread` + `↳ ●@ bob  shipped the auth patch 2m` | **AgentParty block** (`show_party`, on by default). Local bridge for Codex + AgentParty workflows: reads the workspace status cache and, when several sessions share a project, the identity field from the config path used by that session's actual shell commands. It never calls AgentParty or makes network requests; config tokens are never rendered, logged, or transmitted. The header answers *am I listening* outright — `◉ watching/serving` (green), `⊘ listener down` (red), `◌ not listening` (grey). The last message gets its own line, prefixed `●` unread / `○` read and `@` when it mentions you. See [AgentParty bridge](agentparty.md). |
| `📚 EN:6.0↑ JA:5.0→` | IELTS band progress (requires [prompt-language-coach](https://github.com/leeguooooo/prompt-language-coach)) |

Colors default to green / yellow / red at `30%` and `70%` — both thresholds configurable.
