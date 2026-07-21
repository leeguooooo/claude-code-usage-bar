# No-quota mode (third-party relay / Bedrock / Vertex)

When Claude Code talks to a **third-party relay** (`ANTHROPIC_BASE_URL` pointed off `api.anthropic.com` — "中转 API") or a cloud backend (`CLAUDE_CODE_USE_BEDROCK` / `CLAUDE_CODE_USE_VERTEX`), Anthropic's official 5h/7d quota headers don't exist, so the two quota bars have nothing real to show. Instead of leaving them empty (or worse, leaking a previous official session's cached numbers), cs switches to a **no-quota layout**: the 5h/7d bars are dropped and the **context window is promoted to its own battery bar**, keeping the bar alive and focused on what *is* real on a relay.

```
classic    ctx[███35%░░░░] | Opus 4.8 | cache COLD
capsule     ⛁ CTX 35% ●  ╱  ◆ Opus 4.8  ╱  cache 59m57s
hairline   › ctx █▃▁ 35% ┊ › Opus 4.8 ┊ cache 59m57s
```

The context bar colors on **70% / 85% used** (green → yellow → red), and the model name, prompt-cache countdown, and live-activity tail render as usual. Detection is automatic (`api_mode = auto`); a transcript heuristic also catches relays whose env var didn't propagate to the statusLine subprocess. Force it where auto-detect misses with `cs config set api_mode on` (or `CS_API_MODE=on` per shell); force the official layout back with `api_mode off`. Inspired by [claude-hud](https://github.com/jarrodwatts/claude-hud)'s context-first display.

Override per-invocation via `--style` / `--theme` flags or `CLAUDE_STATUSBAR_STYLE` / `CLAUDE_STATUSBAR_THEME` env vars.

## Relay account balance

When a relay exposes an OpenAI-compatible billing endpoint, cs shows your remaining
balance as a fuel-gauge bar (`bal[████ 52%] $26.00`). See the `bal` row in the
[segment reference](segments.md) for how it's probed and how to toggle it.
