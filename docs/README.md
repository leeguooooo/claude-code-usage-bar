# claude-statusbar documentation

Reference docs for [`claude-statusbar`](../README.md). Start with the main
[README](../README.md) for the pitch and quick start; the guides below go deep.

## Getting started
- [Install](install.md) — PyPI, one-shot installer, skill-only, plugin marketplace, Codex bridge
- [What it shows](segments.md) — full per-segment reference table
- [Styles & themes](styles-and-themes.md) — 3 styles × 9 themes, previews, slash commands
- [Configuration](configuration.md) — config file, all `show_*` keys, env vars, JSON output, CLI cheatsheet

## Surfaces & modes
- [Desktop HUD (`cs hud`)](desktop-hud.md) — macOS floating panel for the Claude desktop app
- [Fast mode (daemon)](daemon.md) — sub-1% CPU daemon, launchd / systemd auto-start
- [No-quota mode](no-quota-mode.md) — relay / Bedrock / Vertex layout, context battery, balance
- [AgentParty / Codex bridge](agentparty.md) — local workspace-presence line

## Reference
- [Cache countdown](cache-countdown.md) — data source + how `cache 4m23s` is computed
- [Troubleshooting](troubleshooting.md) — `cs doctor`, common problems, upgrading

## Contributing & project docs
- [Contributing guide](../CONTRIBUTING.md)
- [Changelog](../CHANGELOG.md)
- [Security policy](../SECURITY.md)
- [Code of conduct](../CODE_OF_CONDUCT.md)
