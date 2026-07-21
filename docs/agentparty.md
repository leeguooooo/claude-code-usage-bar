# Claude Code vs Codex support & the AgentParty bridge

`cs` supports Claude Code and Codex in different ways. Claude Code has a native
`statusLine` hook that streams quota/session data into `cs`; Codex does not
provide that same Claude Code payload. Codex support therefore focuses on the
AgentParty bridge: AgentParty writes local workspace state, and `cs` can show
that channel/listener/unread context without making network calls.

| Runtime | What `cs` can show | Data source | Setup |
|---------|--------------------|-------------|-------|
| Claude Code | 5h/7d quota, reset timers, model/context, prompt-cache age, session cost, project/git line, activity lines, and optional AgentParty block | Claude Code `statusLine` stdin plus local caches | `pip install claude-statusbar && cs --setup` |
| Codex + AgentParty | AgentParty channel, identity, listener state, unread count, and last-message preview | `~/.agentparty/state/<workspaceId>/statusline.json` written by AgentParty | Join/send/watch with `party`; keep `show_party` enabled |
| Codex without AgentParty | No Codex quota/session accounting from this package | None | Use Codex's own UI/status surfaces |

The AgentParty bridge is local-only: it does not read AgentParty tokens, does
not call `party`, and does not contact the network during render.

## The AgentParty / Codex line

When AgentParty has initialized the same workspace, `cs` adds a local-only line
under the project identity. This is the Codex-facing integration point: Codex
or another AgentParty writer updates the local cache, and the statusbar reads it
on the next render.

```text
#agentparty · ⬡ xdream-agent · ◉ serving · 3 unread
   ↳ ●@ bob  shipped the auth patch 2m
```

The statusbar only reads `~/.agentparty/state/<workspaceId>/statusline.json`.
It does not call the AgentParty CLI, read tokens, or make network requests. If
the cache is older than 10 minutes, or the recorded listener pid is gone, the
line degrades with `stale` / `down` instead of pretending the listener is live.
Turn it off with `cs config set show_party false`.

Claude Code support remains the full native `statusLine` integration configured
by `cs --setup`; Codex support is this local AgentParty bridge line.

## Codex setup

Codex support is intentionally local and narrow: `cs` can show the AgentParty
context for the current workspace when AgentParty has written
`~/.agentparty/state/<workspaceId>/statusline.json`.

This does **not** turn Codex into a Claude Code `statusLine` source, and it does
not add OpenAI quota/session accounting. The Claude Code quota, context, cache,
tool, and session fields still come from Claude Code's native statusLine stdin.
The Codex/AgentParty bridge only adds workspace presence: channel, human/agent
identity, listener mode, unread count, and last-message preview.

```text
#agentparty · ⬡ xdream-agent · ◉ serving · 3 unread
   ↳ ●@ bob  shipped the auth patch 2m
```

Disable it with `cs config set show_party false`.
