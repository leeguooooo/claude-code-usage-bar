# Draft: feature request for anthropics/claude-code

> 起草于 2026-07-02。发布与否由 leo 决定:`gh issue create -R anthropics/claude-code
> --title "..." --body-file docs/upstream-fr-statusline-focused-agent.md`(去掉这段引言)。

**Title:** statusLine: expose the focused subagent's model/context when viewing an agent pane

## Problem

The statusLine command receives a JSON payload describing the main session
(`model`, `context_window`, `cost`, …). When the user switches the UI to a
subagent pane (the agents panel, `← for agents`), the statusLine keeps
rendering the main loop's model and context window — there is no field
indicating which agent pane is focused, and no per-agent context data.

For users who run several subagents on different models (e.g. main loop on
Fable 5, a changelog writer on Haiku), the status line is misleading while a
subagent pane is focused: it shows the wrong model and the wrong context
usage.

## Request

Add to the statusLine stdin payload:

```json
"focused_agent": {
  "name": "changelog-writer",
  "agent_type": "general-purpose",
  "model": {"id": "claude-haiku-4-5", "display_name": "Haiku 4.5"},
  "context_window": {"used_percentage": 12, "context_window_size": 200000},
  "started_at": 1782960000
}
```

- `null` / absent when the main pane is focused (backward compatible).
- Re-invoke the statusLine command on pane focus change (it already re-invokes
  on model change and cost updates).

## Workarounds today (both partial)

- Parsing the session transcript shows *which* agents are running and for how
  long, but not which pane the user is looking at (focus is UI-internal).
- Subagent transcripts are separate files; without a pointer from the payload
  there is no reliable mapping from "the pane I'm viewing" to a transcript.

Observed on Claude Code v2.1.198 (macOS). Payload fields checked:
`session_id, transcript_path, cwd, prompt_id, effort, session_name, model,
workspace, version, output_style, cost, context_window, exceeds_200k_tokens,
fast_mode, thinking, rate_limits` — nothing agent-focus related.
