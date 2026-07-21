# Desktop HUD (`cs hud`)

> **macOS only.** A floating panel that docks to the bottom-right of the **Claude
> desktop app** — for when you live in the desktop client instead of the terminal.

The desktop app has no `statusLine` hook, so the HUD is a separate always-on-top
window. It reads the **official** 5h / 7d usage the desktop app itself samples
every 5 minutes into `plan-usage-history.json` — the same numbers the terminal
bar shows, not an estimate — plus your active AgentParty channels.

<img width="209" height="63" alt="collapsed HUD pill" src="https://github.com/user-attachments/assets/4bcf4c8d-e919-416a-8356-daa4d5c1a966" />
<img width="1257" height="539" alt="expanded HUD panel" src="https://github.com/user-attachments/assets/fcdea929-5e85-4f1a-982e-ba431d8a80d1" />

```bash
pip install 'claude-statusbar[hud]'   # adds PyObjC (macOS GUI deps)
cs hud install                        # launchd: auto-start on login + keep-alive
```

- **Collapsed pill** — `5h 26% · 7d 22%` + a status dot. Click to expand.
- **Expanded panel** — orange 5h / 7d gradient bars with reset countdowns, and a
  scrollable list of active AgentParty channels (unread count + latest message).
  Click a channel row to **lock** it as the one shown in the collapsed pill.
- **Drag** it anywhere — the position is remembered. It hides itself when the
  Claude desktop app isn't open.

| Command | What it does |
|---------|--------------|
| `cs hud install` | Install the launchd agent — auto-start on login + crash-restart |
| `cs hud start` | Run in the foreground (what the launchd service calls) |
| `cs hud stop` | Stop the running HUD |
| `cs hud uninstall` | Remove the launchd agent |

Everything is local: official usage from the desktop app's own cache, AgentParty
from `~/.agentparty/state/`. No network calls, no credentials read.
