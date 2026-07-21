# Claude Status Bar

[![PyPI](https://img.shields.io/pypi/v/claude-statusbar.svg)](https://pypi.org/project/claude-statusbar/)
[![Python](https://img.shields.io/pypi/pyversions/claude-statusbar.svg)](https://pypi.org/project/claude-statusbar/)
[![Downloads](https://static.pepy.tech/badge/claude-statusbar/month)](https://pepy.tech/project/claude-statusbar)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/leeguooooo/claude-code-usage-bar?style=social)](https://github.com/leeguooooo/claude-code-usage-bar/stargazers)

Lightweight usage monitor for Claude Code. It shows your 5h / 7d rate-limit
usage, reset timers, current model, context window, prompt-cache freshness, and
(optionally) session cost — inline in Claude Code's status line, **or** in a
floating HUD on the Claude desktop app. A local AgentParty bridge adds Codex
workflow presence (channel, listener, unread) from a local cache.

3 styles × 9 themes, configurable in one command. Auto-updates from PyPI.

## Claude Code (terminal)

```bash
pip install claude-statusbar     # or: uv tool install / pipx install
cs --setup                       # wires the statusLine hook + installs the skill
```

Restart Claude Code and the bar appears at the bottom:

```
5h[   27%    ]⏰1h28m →42% | 7d[   79%    ]⏰11h28m →88% | Opus 4.8(350.0k/1.0M) | cache 4m23s
```

![claude-statusbar live demo](docs/images/hero.gif)

> 📖 **Deep dive:** [Is that `cache 4m23s` line actually accurate? — how the prompt-cache countdown is computed](https://blog.leeguoo.com/en/posts/claude-statusbar-cache-countdown/)

Other install paths (one-shot installer, skill-only, plugin marketplace,
Codex/AgentParty) are in the [install guide](docs/install.md).

## Claude desktop app (macOS) — `cs hud`

The desktop app has no status line, so `cs hud` adds an always-on-top floating
panel with the same **official** 5h / 7d usage (sampled by the desktop app
itself, not an estimate) and your active AgentParty channels.

```bash
pip install 'claude-statusbar[hud]'   # adds PyObjC (macOS GUI deps)
cs hud install                        # launchd: auto-start on login + keep-alive
```

<img width="209" height="63" alt="collapsed HUD pill" src="https://github.com/user-attachments/assets/4bcf4c8d-e919-416a-8356-daa4d5c1a966" />
<img width="1257" height="539" alt="expanded HUD panel" src="https://github.com/user-attachments/assets/fcdea929-5e85-4f1a-982e-ba431d8a80d1" />

Collapsed pill → click to expand → drag anywhere; it hides when the desktop app
isn't open. Full details in the [Desktop HUD guide](docs/desktop-hud.md).

## What it shows

```
5h[   27%    ]⏰1h28m →42% | 7d[   79%    ]⏰11h28m →88% | Opus 4.8(350.0k/1.0M) | cache 4m23s | $ 1.42
⤷ claude-code-usage-bar ⎇ main● · +182 -47 · ⏱ 12m · v3.12.0
⚙ effort:high · think:on · fast:off · style:default
```

- **Line 1** — 5h / 7d rate-limit usage + reset timers + end-of-window
  projections, model & context window, prompt-cache countdown, optional session
  cost / relay balance.
- **Line 2** — project + git branch, session `+/−` lines, duration, version.
- **Line 3** — session mode (effort / thinking / fast / style).
- Plus optional **activity** and **AgentParty** lines.

The full per-segment breakdown — every icon, color threshold, and toggle — is in
the [segment reference](docs/segments.md).

## Documentation

| Guide | What's inside |
|-------|---------------|
| [Install](docs/install.md) | PyPI, one-shot installer, skill-only, plugin, Codex bridge |
| [What it shows](docs/segments.md) | Full per-segment reference table |
| [Styles & themes](docs/styles-and-themes.md) | 3 styles × 9 themes, previews, slash commands |
| [Configuration](docs/configuration.md) | Config file, all `show_*` keys, env vars, JSON output, CLI cheatsheet |
| [Desktop HUD (`cs hud`)](docs/desktop-hud.md) | macOS floating panel for the Claude desktop app |
| [Fast mode (daemon)](docs/daemon.md) | Sub-1% CPU daemon, launchd / systemd auto-start |
| [No-quota mode](docs/no-quota-mode.md) | Relay / Bedrock / Vertex layout, context battery, balance |
| [AgentParty / Codex bridge](docs/agentparty.md) | Local workspace-presence line |
| [Cache countdown](docs/cache-countdown.md) | Data source + how `cache 4m23s` is computed |
| [Troubleshooting](docs/troubleshooting.md) | `cs doctor`, common problems, upgrading |

## Comparison with alternatives

There are a few good Claude Code usage monitors. They solve overlapping but distinct problems — pick the one that matches *where* you want the information.

| Tool | Lives in | Optimized for |
|---|---|---|
| **claude-statusbar (`cs`)** | Claude Code's `statusLine` (one line at the bottom) | Glanceable while you work; zero context-switching |
| [ccusage](https://github.com/ryoppippi/ccusage) | Standalone TUI in a separate terminal window | Long-form usage analytics, cost breakdowns over weeks |
| [Claude Code Usage Monitor](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor) | Standalone TUI with predictive burn-rate | Real-time burn-rate forecast for paid plans |

`cs` is intentionally one line of color and one decision per second. If you want a dashboard with charts, daily/weekly aggregates, and burn-rate prediction, run a TUI in a side pane. The two coexist nicely.

## Integrations

### prompt-language-coach

Install the [prompt-language-coach](https://github.com/leeguooooo/prompt-language-coach) Claude Code plugin to get IELTS band progress tracking. After setup, the status bar automatically shows your current writing level and trend:

```
... | Opus 4.8(350k/1M) | 📚 EN:6.0↑ JA:5.0→
```

- `↑` improved from last session · `↓` dropped · `→` no change
- No configuration needed — the segment appears automatically when `~/.claude/language-progress.json` exists.

## Latest release

**Unreleased** — **Desktop HUD** (`cs hud`, macOS): a floating panel for the **Claude desktop app** showing official 5h / 7d usage + your active AgentParty channels, with launchd auto-start. See [Desktop HUD](docs/desktop-hud.md).

**v3.29.12** (2026-07-15) — AgentParty status is session-correct end to end.

**v3.28.0** (2026-07-09) — AgentParty / Codex bridge line (`show_party`).

**v3.11.0** (2026-06-02) — rate-limit projections (`→NN%`).

**v3.6.0** (2026-05-08) — `cs --setup` defaults to daemon (fast) mode.

📋 **Full changelog:** [CHANGELOG.md](CHANGELOG.md) · [GitHub Releases](https://github.com/leeguooooo/claude-code-usage-bar/releases) — every version's changes, also linked from the [PyPI page](https://pypi.org/project/claude-statusbar/).

## Contributing

PRs welcome. The full contributor guide — local setup, test commands, architecture map, coding conventions, release flow — lives in [CONTRIBUTING.md](CONTRIBUTING.md). Security issues: see [SECURITY.md](SECURITY.md).

Quick start:

```bash
git clone https://github.com/leeguooooo/claude-code-usage-bar
cd claude-code-usage-bar
uv sync
PYTHONPATH=src uv run pytest tests/   # 320+ tests, ~1.5s
```

Render path is hot (60×/min at `refreshInterval: 1`) — `tests/test_import_perf.py` pins which modules can't be imported on the fast path. Read CONTRIBUTING.md before adding dependencies.

## Acknowledgments

- [@marcwimmer](https://github.com/marcwimmer) — original `show_cache_age` widget ([#9](https://github.com/leeguooooo/claude-code-usage-bar/pull/9))
- [claude-monitor](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor) — token-usage analysis library used as the optional fast-path data source

## Contributors

<a href="https://github.com/leeguooooo/claude-code-usage-bar/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=leeguooooo/claude-code-usage-bar" alt="Contributors" />
</a>

Made with [contrib.rocks](https://contrib.rocks).

---

## License

MIT

## Star History

<a href="https://star-history.com/#leeguooooo/claude-code-usage-bar&Date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/images/star-history-dark.svg">
    <img alt="Star history" src="docs/images/star-history.svg">
  </picture>
</a>

<sub>Static snapshot taken at v3.3.x; <a href="https://star-history.com/#leeguooooo/claude-code-usage-bar&Date">click for live chart</a>.</sub>
