# Claude Status Bar

[![PyPI](https://img.shields.io/pypi/v/claude-statusbar.svg)](https://pypi.org/project/claude-statusbar/)
[![Python](https://img.shields.io/pypi/pyversions/claude-statusbar.svg)](https://pypi.org/project/claude-statusbar/)
[![Downloads](https://static.pepy.tech/badge/claude-statusbar/month)](https://pepy.tech/project/claude-statusbar)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/leeguooooo/claude-code-usage-bar?style=social)](https://github.com/leeguooooo/claude-code-usage-bar/stargazers)

Lightweight Claude Code status-line monitor. Shows your 5h / 7d rate-limit usage, reset timers, current model, context window, prompt-cache freshness, and (optionally) session cost — in a single compact line driven by Claude Code's `statusLine` hook.

```
5h[   27%    ]⏰1h28m | 7d[   79%    ]⏰11h28m | Opus 4.7(350.0k/1.0M) | cache 0s
```

3 styles × 7 themes, configurable in one command. Auto-updates from PyPI. New in **v3.2**: a daemon mode that drops 1 Hz refresh CPU from ~6% to ~2% — same status line, ~5× cheaper.

## Contents
- [What's new in v3.2](#whats-new-in-v32)
- [What it shows](#what-it-shows)
- [Install](#install)
- [Styles & themes](#styles--themes)
- [Configuration](#configuration-file)
- [Fast mode (daemon)](#fast-mode--for-refreshinterval-1)
- [Slash commands](#slash-commands-inside-claude-code)
- [`cs doctor` — self-diagnostic](#cs-doctor--self-diagnostic)
- [Usage cheatsheet](#usage)
- [Environment variables](#environment-variables)
- [Troubleshooting](#troubleshooting)
- [Upgrading](#upgrading)
- [Integrations](#integrations)
- [Contributing](#contributing)
- [Acknowledgments](#acknowledgments)

## What's new in v3.2

- **Daemon fast-mode** — `cs --setup --fast` swaps the statusLine command to `cs render` backed by a long-lived `cs daemon`. At `refreshInterval: 1` this cuts continuous CPU from ~6% to ~2%, render wall-clock from ~60ms to ~5ms. Crash-safe (auto-falls-back to inline render if the daemon dies; lazy-respawns).
- **OS-managed daemon** — `cs daemon install` installs a launchd agent (macOS) or systemd user unit (Linux) so the daemon auto-starts on login and is restarted on crash by the OS.
- **`cache 15s` segment** — opt-in via `cs config set show_cache_age true`. Shows time since Claude's last assistant turn, flips to `cache COLD` past Anthropic's 5-minute prompt-cache TTL. Configurable TTL via `cs config set cache_ttl_seconds 3600` for users on the 1-hour extended cache.
- **`cs doctor` 1Hz hint** — detects `refreshInterval ≤ 2s` with the inline command and recommends `cs --setup --fast`.
- **Import-shaving on the inline path** — even users who don't opt into daemon mode get ~30% faster renders.

Existing users: nothing changes by default. Daemon mode is opt-in.

## What it shows

```
5h[   27%    ]⏰1h28m | 7d[   79%    ]⏰11h28m | Opus 4.7(350.0k/1.0M) | cache 0s | $ 1.42
```

| Segment | Meaning |
|---------|---------|
| `5h[27%]` | 5-hour rate-limit usage (rolling window from Anthropic API headers) |
| `⏰1h28m` | Time until the 5-hour window resets |
| `7d[79%]` | 7-day rate-limit usage |
| `⏰11h28m` | Time until the 7-day window resets |
| `Opus 4.7(350.0k/1.0M)` | Model name + current context window usage |
| `cache 0s` / `cache COLD` | Prompt-cache age — green warm, red cold (opt-in: `cs config set show_cache_age true`) |
| `$ 1.42` | Session cost so far in USD (opt-in: `cs config set show_cost true`) |
| `📚 EN:6.0↑ JA:5.0→` | IELTS band progress (requires [prompt-language-coach](https://github.com/leeguooooo/prompt-language-coach)) |

Colors default to green / yellow / red at `30%` and `70%` — both thresholds configurable.

## Install

### One-line install (recommended)

```bash
curl -fsSL "https://raw.githubusercontent.com/leeguooooo/claude-code-usage-bar/main/web-install.sh?v=$(date +%s)" | bash
```

Installs the package, configures Claude Code's `statusLine`, sets up shell aliases. Restart Claude Code to see the bar.

### Package managers

```bash
pip install claude-statusbar     # pip
uv tool install claude-statusbar # uv
pipx install claude-statusbar    # pipx
```

Then add to `~/.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "cs",
    "refreshInterval": 30
  }
}
```

`refreshInterval` is in seconds. Set it to `1` if you enable [`show_cache_age`](#configuration-file) and want the cache timer to tick visibly — and pair that with [fast mode](#fast-mode--for-refreshinterval-1).

## Styles & themes

The default style (`classic`) stays the same forever. Two alternative styles, plus a palette of seven themes, are opt-in.

```bash
cs --style capsule  --theme graphite   # try once
cs --style hairline --theme twilight   # try once
cs config set style capsule            # persist
cs config set theme twilight
cs styles                              # list available styles
cs themes                              # list available themes
cs preview                             # render every style × theme together
```

### Styles

| Style | Look |
|-------|------|
| `classic`  | Original `[bar] \| pipe` engineering layout. Default. |
| `capsule`  | Each metric is a colored pill — type badge (`◷ 5H` / `☷ 7D` / `◆` / `📚`) on the left, value, severity dot on the right. Subway-signage feel. |
| `hairline` | One-character mini-bar (`▁▃▆█`) per metric, dashed `┊` separators, tight typography. Maximally calm. |

**Capsule** — `graphite` · `twilight` · `nord` · `dracula` · `sakura` · `linen` · `mono`

![capsule + graphite](docs/images/capsule-graphite.svg)
![capsule + twilight](docs/images/capsule-twilight.svg)
![capsule + nord](docs/images/capsule-nord.svg)
![capsule + dracula](docs/images/capsule-dracula.svg)
![capsule + sakura](docs/images/capsule-sakura.svg)
![capsule + linen](docs/images/capsule-linen.svg)
![capsule + mono](docs/images/capsule-mono.svg)

**Hairline** — same theme set, different layout

![hairline + graphite](docs/images/hairline-graphite.svg)
![hairline + nord](docs/images/hairline-nord.svg)
![hairline + dracula](docs/images/hairline-dracula.svg)
![hairline + sakura](docs/images/hairline-sakura.svg)
![hairline + mono](docs/images/hairline-mono.svg)

**Classic** — kept identical to the pre-v2.7 look

![classic + graphite](docs/images/classic-graphite.svg)

### Themes

| Theme | Vibe |
|-------|------|
| `graphite` | Cool dark graphite — default, fits most dark terminals |
| `twilight` | Soft purples/roses — warm dark |
| `linen`    | Cream/beige — for light terminal themes |
| `nord`     | Nord palette — familiar Arctic blue |
| `dracula`  | Dracula palette — high-contrast purple/black |
| `sakura`   | Pink/cream — soft, light backgrounds |
| `mono`     | Pure grayscale — no chromatic distraction |

Style and theme are independent: any of the **3 styles × 7 themes = 21 combinations**.

### Slash commands inside Claude Code

After running `cs --setup` (or `cs install-commands`), the following slash commands work inside Claude Code:

| Slash command | What it does |
|---------------|--------------|
| `/statusbar`               | Show current config + lists styles/themes |
| `/statusbar-preview`       | Render every style × theme combination using your real data |
| `/statusbar-style <name>`  | Switch style (`classic` / `capsule` / `hairline`) |
| `/statusbar-theme <name>`  | Switch theme (`graphite` / `twilight` / `linen` / `nord` / `dracula` / `sakura` / `mono`) |
| `/statusbar-doctor`        | Self-diagnostic — paste output in bug reports |
| `/statusbar-reset`         | Wipe config back to defaults |

### Configuration file

Persisted to `~/.claude/claude-statusbar.json`:

```json
{
  "style": "capsule",
  "theme": "twilight",
  "density": "regular",
  "auto_compact_width": 100,
  "show_weekly": true,
  "show_language": true,
  "show_cost": false,
  "show_cache_age": false
}
```

| Key | Values | What it does |
|-----|--------|--------------|
| `style` | `classic` / `capsule` / `hairline` | Layout |
| `theme` | `graphite` / `twilight` / `linen` / `nord` / `dracula` / `sakura` / `mono` | Colors |
| `density` | `compact` / `regular` / `cozy` | Padding around segments (capsule + hairline only) |
| `auto_compact_width` | integer (e.g. `100`) | Force `hairline` when terminal narrower than this. `0` = disabled |
| `show_weekly`, `show_language` | bool | Hide individual segments |
| `show_cost` | bool, default `false` | Append a `$ X.XX` segment with the current session's cost (from Claude Code's stdin payload). Opt-in because the "session" boundary is what Claude Code reports — not necessarily what you intuitively call one |
| `show_cache_age` | bool, default `false` | Append a `cache 15s` (green) / `cache COLD` (red) segment showing how long since Claude's last assistant turn. Anthropic's prompt cache TTL is 5 minutes — the segment flips to `COLD` past that. Useful to see at a glance whether your next request will hit the warm cache. **Requires `"refreshInterval": N` in your `~/.claude/settings.json` `statusLine` block** (e.g. `30`) — without it Claude Code only re-renders on activity, so the value freezes. Contributed by [@marcwimmer](https://github.com/marcwimmer) in [#9](https://github.com/leeguooooo/claude-code-usage-bar/pull/9). |
| `cache_ttl_seconds` | int, default `300` | TTL the `show_cache_age` segment uses to decide warm vs. `COLD`. Defaults to Anthropic's 5-minute prompt cache. Set to `3600` if you've enabled the [1-hour extended cache](https://docs.claude.com/en/docs/build-with-claude/prompt-caching) via `ENABLE_PROMPT_CACHING_1H`. |

Set via `cs config set <key> <value>`. Wipe everything back to defaults with `cs config reset`.

Override per-invocation via `--style` / `--theme` flags or `CLAUDE_STATUSBAR_STYLE` / `CLAUDE_STATUSBAR_THEME` env vars.

## Fast mode — for `refreshInterval: 1`

If you've set `"refreshInterval": 1` in `settings.json` (so the cache-age widget ticks every second), the default `cs` command runs ~45ms per render = ~4% CPU continuously. Fast mode brings that down to ~3-5ms per render = under 1% CPU by keeping a long-lived `cs daemon` that pre-renders into `~/.cache/claude-statusbar/rendered.ansi`. The statusLine command becomes `cs render` — a thin reader that just `cat`s the file.

```bash
cs --setup --fast        # writes settings.json + spins up the daemon
cs daemon status         # check it's alive
cs daemon stop           # stop the daemon (statusLine falls back to inline)
cs daemon start          # start it again
```

Crash safety: if the daemon dies or freezes, `cs render` notices `rendered.meta.json` is older than 5s and falls back to inline render — and lazily re-spawns the daemon in the background. You never see a frozen status line.

To revert: `cs --setup` (no `--fast`) restores the bare-`cs` legacy command.

### Optional: auto-start on login (launchd / systemd)

Lazy-spawn (above) covers most cases — the daemon comes up on first `cs render`. If you want stronger guarantees (auto-start at login, OS restarts the daemon on crash, survives reboots without `cs render` needing to fire first):

```bash
cs daemon install        # installs ~/Library/LaunchAgents (macOS) or
                          # ~/.config/systemd/user (Linux), starts the daemon
cs daemon service        # report whether the OS-level service is registered
cs daemon uninstall      # remove the LaunchAgent / systemd unit
```

On macOS, the LaunchAgent has `KeepAlive=true` and `ThrottleInterval=10` — kill the daemon and launchd respawns it within 10 seconds. On Linux, the systemd user unit uses `Restart=always` (you may need `loginctl enable-linger $USER` for the daemon to survive logout).

## `cs doctor` — self-diagnostic

If the status bar isn't behaving the way you expect, run:

```bash
cs doctor
```

It prints (with red ✗ for anything off):

- Which `cs` binary the OS will resolve, plus its version + Python interpreter
- Whether `~/.claude/settings.json` has *our* statusLine entry (vs missing / vs another tool's)
- How fresh `~/.cache/claude-statusbar/last_stdin.json` is (so you can tell if Claude Code is actually pushing data)
- If the daemon is running (fast mode) — its pid and how stale `rendered.ansi` is
- Terminal size and `TERM`
- Current resolved `style` / `theme` / all `show_*` toggles
- Slash commands installed under `~/.claude/commands/`

Paste the output verbatim in any bug report — it's almost always enough to diagnose remotely.

## Install as a Claude Code plugin

The repo ships a `.claude-plugin/plugin.json`, distributed via the **leeguooooo/plugins** marketplace. Inside Claude Code:

```
/plugin marketplace add leeguooooo/plugins
/plugin install claude-statusbar@leeguooooo-plugins
```

You still need the `cs` CLI (`pip install claude-statusbar` or `uv tool install claude-statusbar`) — the plugin only carries the slash commands; the heavy lifting is the Python package.

## Usage

```bash
cs                              # render the status line (default command)
cs --style capsule              # render with a one-off style
cs --theme twilight             # render with a one-off theme

# Configuration
cs config show                  # show all persistent config
cs config set style hairline    # persist style → ~/.claude/claude-statusbar.json
cs config set theme linen       # persist theme
cs config set show_cost true    # session $ cost segment
cs config set show_cache_age true   # prompt-cache age segment (needs refreshInterval)
cs config set cache_ttl_seconds 3600  # for users on Anthropic's 1h cache
cs config reset                 # wipe config back to defaults

# Discovery
cs styles                       # list available styles
cs themes                       # list available themes
cs preview                      # render every style × theme with YOUR real data

# Daemon mode (v3.2+, opt-in)
cs --setup --fast               # switch statusLine to `cs render` + start daemon
cs daemon start                 # start daemon (manual)
cs daemon stop                  # stop daemon
cs daemon status                # pid + rendered.ansi freshness
cs daemon install               # install LaunchAgent (macOS) / systemd unit (Linux)
cs daemon uninstall             # remove the OS-level service
cs daemon service               # report whether the OS service is registered

# Diagnostics + flags
cs doctor                       # self-diagnostic — paste output in bug reports
cs --json-output                # machine-readable JSON
cs --no-color                   # disable ANSI colors
cs --warning-threshold 40 --critical-threshold 85
cs --no-auto-update             # skip the per-day PyPI version check
```

`--plan` still exists for older scripts, but is deprecated and no longer changes the rendered output.

### Environment variables

| Variable | Effect |
|----------|--------|
| `CLAUDE_STATUSBAR_STYLE=capsule` | Render with this style (overrides config file) |
| `CLAUDE_STATUSBAR_THEME=twilight` | Render with this theme (overrides config file) |
| `CLAUDE_STATUSBAR_NO_UPDATE=1` | Disable automatic update checks |
| `CLAUDE_STATUSBAR_WARNING_THRESHOLD=40` | Switch from green to yellow at 40% |
| `CLAUDE_STATUSBAR_CRITICAL_THRESHOLD=85` | Switch from yellow to red at 85% |
| `NO_COLOR=1` | Disable ANSI colors |

`CLAUDE_PLAN` is still accepted for legacy compatibility, but it no longer changes the rendered status line.

### JSON output

Use `--json-output` if you want a machine-readable payload instead of the formatted status line:

```bash
cs --json-output
```

## Data source

Rate-limit percentages come directly from **Anthropic's official API headers**, surfaced into the JSON payload Claude Code injects on stdin to every `statusLine` command. Context-window usage comes from the same payload. The optional `cache 15s` segment is computed locally by tail-reading the active transcript JSONL — Anthropic's prompt cache TTL is 5 minutes by default ([Mar 2026 change](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)) or 1 hour with `ENABLE_PROMPT_CACHING_1H`.

Requires Claude Code `v2.1.80+`.

## Troubleshooting

**Status line doesn't appear after install** — Restart Claude Code (settings.json is read at session start). If still missing, run `cs doctor` and check the `statusLine entry` row.

**`cs doctor` says "missing"** — A Claude Code upgrade can wipe `statusLine` from `~/.claude/settings.json`. Run `cs --setup` (or `cs --setup --fast` if you want daemon mode) to restore it. The package also self-heals once per day automatically.

**Numbers stuck / not updating** — Two possibilities:
1. `refreshInterval` not set — Claude Code only re-renders on activity. Add `"refreshInterval": 30` (or `1` for live cache-age).
2. Daemon mode running stale data — `cs daemon stop && cs daemon start`. Or just `cs doctor` and check `daemon` row freshness.

**Cache-age segment shows `cache 0s` and never moves** — `refreshInterval` is unset; Claude Code only re-invokes the statusLine on each user/assistant turn. Set `"refreshInterval": 1` in settings.json. For 1Hz refresh you'll also want `cs --setup --fast` so the per-second invocation stays cheap.

**`cs --setup --fast` then daemon shows wrong rate-limits** — Fixed in v3.2.1. Upgrade with `pip install -U claude-statusbar`.

**Auto-update is annoying / blocked** — `export CLAUDE_STATUSBAR_NO_UPDATE=1` in your shell rc.

For anything else: open a [GitHub issue](https://github.com/leeguooooo/claude-code-usage-bar/issues) with the output of `cs doctor` attached — it captures version, paths, settings.json state, daemon state, and recent cache freshness in one paste.

## Upgrading

Auto-updates once per day from PyPI. To upgrade manually:

```bash
pip install -U claude-statusbar
# or
uv tool upgrade claude-statusbar
```

To disable auto-updates: `export CLAUDE_STATUSBAR_NO_UPDATE=1`

## Integrations

### prompt-language-coach

Install the [prompt-language-coach](https://github.com/leeguooooo/prompt-language-coach) Claude Code plugin to get IELTS band progress tracking. After setup, the status bar automatically shows your current writing level and trend:

```
... | Opus 4.7(350k/1M) | 📚 EN:6.0↑ JA:5.0→
```

- `↑` improved from last session · `↓` dropped · `→` no change
- No configuration needed — the segment appears automatically when `~/.claude/language-progress.json` exists.

## Contributing

PRs welcome. Quick guide:

```bash
git clone https://github.com/leeguooooo/claude-code-usage-bar
cd claude-code-usage-bar
pip install -e .                    # editable install
pytest                              # 240+ tests, all should pass
PYTHONPATH=src python3 -m pytest -q tests/test_import_perf.py  # perf regression guards
```

A few conventions to know:
- Render path is hot — every module loaded at import time multiplies its cost by `60×/min` at `refreshInterval: 1`. `tests/test_import_perf.py` pins this; if your change adds a heavy stdlib import on the path, the test fails.
- Atomic file writes use the helper in `cache.py` (`atomic_write_text`) — never `path.write_text(...)` for state files.
- The daemon path (`daemon.py` + `render_thin.py`) is opt-in. The legacy inline path (`core.py:main()`) must stay working without the daemon.
- New config keys: bump `config.StatusbarConfig`, `VALID_KEYS`, the `_*_KEYS` sets, and document in this README.

## Acknowledgments

- [@marcwimmer](https://github.com/marcwimmer) — original `show_cache_age` widget ([#9](https://github.com/leeguooooo/claude-code-usage-bar/pull/9))
- [claude-monitor](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor) — token-usage analysis library used as the optional fast-path data source

---

## License

MIT

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=leeguooooo/claude-code-usage-bar&type=Date)](https://star-history.com/#leeguooooo/claude-code-usage-bar&Date)
