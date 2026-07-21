# Install

There are two installers. The **standalone binary** needs nothing on your
machine (no Python); the **pip/uv** path installs the Python package.

## Claude Code: standalone binary (recommended, no Python required)

```bash
curl -fsSL https://raw.githubusercontent.com/leeguooooo/claude-code-usage-bar/main/install.sh | bash
```

[`install.sh`](../install.sh) detects your OS + CPU arch, downloads the matching
prebuilt `cs` binary from the latest GitHub Release, **verifies its SHA-256**,
installs it to `~/.local/bin` (no `sudo`; everything under `$HOME`), and runs
`cs --setup` to wire the statusLine + slash commands. The binary is a single
self-contained executable — **no Python, no pip, no dependencies**.

Prebuilt targets: **macOS arm64 / x86_64, Linux x86_64**. On any other platform
(Linux arm64, Windows) the script automatically falls back to the pip installer
below.

Security-conscious? Download and read it first:

```bash
curl -fsSL https://raw.githubusercontent.com/leeguooooo/claude-code-usage-bar/main/install.sh -o /tmp/cs.sh
less /tmp/cs.sh    # audit it
bash /tmp/cs.sh
```

Update later by re-running the same one-liner. (The binary can't `pip`-upgrade
itself; `cs upgrade` prints this command for you.) The desktop HUD (`cs hud`)
is **not** in the binary — it needs PyObjC; install it via the pip extra below.

## Claude Code: pip / uv (the Python package)

```bash
pip install claude-statusbar     # or: uv tool install claude-statusbar
                                 # or: pipx install claude-statusbar
cs --setup                       # wires the statusLine hook + installs the skill
```

There's also a pip-based one-shot script,
[`web-install.sh`](../web-install.sh), that auto-detects `uv` / `pipx` / `pip`
(and bootstraps `uv` if you have none), then runs `cs --setup` — it needs
Python 3.9+:

```bash
curl -fsSL https://raw.githubusercontent.com/leeguooooo/claude-code-usage-bar/main/web-install.sh | bash
```

Restart Claude Code to see the bar. `cs --setup` writes the following into `~/.claude/settings.json` (existing files are backed up first, other keys are preserved):

```json
{
  "statusLine": {
    "type": "command",
    "command": "cs render",
    "refreshInterval": 1
  }
}
```

Since v3.6.0 `cs --setup` defaults to daemon mode (`cs render` + `refreshInterval: 1`), which keeps CPU under 1% continuously while ticking the cache-age countdown every second. The daemon is auto-started by `cs --setup` and lazy-respawns on `cs render` if it ever dies, so you never see a frozen bar. Opt out with `cs --setup --inline` (writes plain `cs`, ~3% CPU at 1Hz) or set `refreshInterval` to a higher value — `cs --setup` preserves any explicit value you've already chosen. See [Fast mode (daemon)](daemon.md) for details.

## Codex: AgentParty local status bridge

Codex support is intentionally local and narrow: `cs` can show the AgentParty
context for the current workspace when AgentParty has written
`~/.agentparty/state/<workspaceId>/statusline.json`. See [AgentParty
bridge](agentparty.md) for the full picture.

```text
#agentparty · ⬡ xdream-agent · ◉ serving · 3 unread
   ↳ ●@ bob  shipped the auth patch 2m
```

Disable it with `cs config set show_party false`.

## Skill-only install (already have `cs`)

If you already have the `cs` binary installed (e.g. via `pip install`) and just want the conversational `claude-statusbar` skill so Claude Code routes natural-language requests like "switch theme to nord" or "余量颜色改成 #4ec85b" to the right `cs` command:

```bash
npx skills add leeguooooo/claude-code-usage-bar -g -y
```

This installs only the skill globally. It does *not* install `cs` itself — the skill's actions all call out to the `cs` CLI, so you still need one of the install paths above for the binary. Use this path when distributing into environments that already manage Python tooling separately, or when you want to update only the skill without touching `cs`.

`cs --setup` already installs the same skill alongside the slash commands, so most users don't need this path.

## Install as a Claude Code plugin

The repo ships a `.claude-plugin/plugin.json`, distributed via the **leeguooooo/plugins** marketplace. Inside Claude Code:

```
/plugin marketplace add leeguooooo/plugins
/plugin install claude-statusbar@leeguooooo-plugins
```

You still need the `cs` CLI (`pip install claude-statusbar` or `uv tool install claude-statusbar`) — the plugin only carries the slash commands; the heavy lifting is the Python package.
