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
Lightweight Claude Code statusLine monitor with switchable styles and 7 color themes.

## Long description
`claude-statusbar` powers the Claude Code statusLine slot at the bottom of every session. It reads Anthropic's official rate-limit headers (5-hour and 7-day windows), context-window usage, and current model directly from the stdin payload Claude Code sends to custom statusLine commands — no API keys, no extra requests.

Three styles cover different aesthetics:
- `classic` — the original `[bar] | pipe` engineering layout (default, never changes)
- `capsule` — colored "transit pill" segments with type badges, severity dots, and themed backgrounds
- `hairline` — Swiss/editorial minimalism with single-character mini-bars and dashed dividers

Seven themes: `graphite`, `twilight`, `linen`, `nord`, `dracula`, `sakura`, `mono` — any theme works with any style (21 combinations, runnable as `cs preview`).

The plugin ships five slash commands (`/statusbar`, `/statusbar-preview`, `/statusbar-style`, `/statusbar-theme`, `/statusbar-reset`) and is backed by the Python CLI `cs` (PyPI: `claude-statusbar`).

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
See `docs/images/*.svg` in the repo (21 self-contained SVG snapshots covering every style × theme combination).

## License
MIT
