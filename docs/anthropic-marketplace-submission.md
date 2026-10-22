# Submission: Anthropic Plugin Directory

> Anthropic's official marketplace (`anthropics/claude-plugins-official`) does not accept direct PRs for external plugins. Submit via the form at https://clau.de/plugin-directory-submission. The fields below are pre-filled with the answers; copy/paste them.

## Plugin name
`claude-statusbar`

## Repository URL
https://github.com/leeguooooo/claude-code-usage-bar

## Homepage
https://github.com/leeguooooo/claude-code-usage-bar

## Category
monitoring

## Author
- Name: leeguooooo
- Email: leeguooooo@gmail.com

## Short description (one sentence)
Lightweight Claude Code statusLine monitor with three switchable looks.

## Long description
`claude-statusbar` powers the Claude Code statusLine slot at the bottom of every session. It reads Anthropic's official rate-limit headers (5-hour and 7-day windows), context-window usage, and current model directly from the stdin payload Claude Code sends to custom statusLine commands — no API keys, no extra requests.

Three looks, previewable with `cs preview`:
- `aurora` with block bars (default) — cells blend green → amber → red by position
- `aurora` with a thin line — same colors, a hairline `━` bar
- `classic` — the original `[bar] | pipe` engineering layout, unchanged

The plugin ships five slash commands (`/statusbar`, `/statusbar-preview`, `/statusbar-style`, `/statusbar-doctor`, `/statusbar-reset`) and is backed by the Python CLI `cs` (PyPI: `claude-statusbar`).

## How to install (for the directory page)
1. `pip install claude-statusbar` (or `uv tool install claude-statusbar`)
2. `cs --setup` — registers the statusLine + installs slash commands
3. Restart Claude Code

## Why it qualifies
- Official Anthropic data only (rate-limit headers via stdin)
- Zero network calls at runtime
- Tiny: under 50KB wheel, no required deps
- Backwards compatible: `classic` style preserved untouched for existing users
- Active maintenance — published to PyPI as `claude-statusbar==2.8.0`
- MIT license

## Screenshots
See `docs/images/{aurora-graphite,aurora-thin-graphite,classic-graphite}.svg` in the repo — one self-contained SVG per look.

## License
MIT
