# Configuration

## Configuration file

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
  "show_balance": true,
  "balance_bar": true,
  "show_cache_age": true,
  "show_project_branch": true,
  "show_party": true,
  "show_todos": true,
  "show_tools": false,
  "show_agents": false,
  "show_duration": false,
  "show_lines": true,
  "show_ahead_behind": false
}
```

| Key | Values | What it does |
|-----|--------|--------------|
| `style` | `classic` / `capsule` / `hairline` | Layout |
| `theme` | 9 themes (see [Styles & themes](styles-and-themes.md)) | Colors |
| `density` | `compact` / `regular` / `cozy` | Segment padding (capsule + hairline only) |
| `auto_compact_width` | int | Force `hairline` below this terminal width; `0` = off |
| `show_cost` | bool, `false` | Append `$ X.XX` session cost (API-equivalent value for subscribers) |
| `show_balance` / `balance_bar` | bool, `true` | No-quota relay balance as a fuel-gauge bar — auto-hidden if the relay doesn't support it |
| `show_cache_age` | bool, `true` | `cache 4m23s` prompt-cache countdown (TTL auto-detected 5m/1h) |
| `show_project_branch` | bool, `true` | Second line: project + branch + `●` dirty dot |
| `show_ahead_behind` | bool, `false` | `↑2↓1` commits ahead/behind on the branch line |
| `show_party` | bool, `true` | AgentParty / Codex bridge line (reads local cache only) |
| `show_todos` | bool, `true` | Activity line: in-progress todo + `done/total` |
| `show_tools` / `show_tool_rollup` | bool, `false` | Active tool / completed-tool frequency rollup |
| `show_projection` / `show_forecast` | bool, `true` | `→NN%` projection / `⚠ETA` at-risk warning chip |
| `show_agents` | bool, `false` | One bottom line per running subagent (Claude Code shows these natively too) |
| `show_duration` / `show_lines` | bool | Session `⏱` duration / `+/−` lines on the identity line |
| `show_version` | bool, `true` | Faint `· vX.Y.Z` (+ amber `↑newver` when a newer PyPI release exists) |
| `show_mode` / `mode_gradient` | bool, `true` | `⚙` session-mode line + effort-tier gradient tint |
| `show_weekly` / `show_language` | bool | Toggle the 7d bar / language-coach segment |
| `bar_shimmer` | bool, `false` | Experimental twinkling starfield on bars (classic only) |
| `api_mode` | `auto` / `on` / `off` | No-quota mode (see [No-quota mode](no-quota-mode.md)); `CS_API_MODE` env overrides |

Full per-key detail is in the [segment reference](segments.md) or `cs config show`. Set with `cs config set <key> <value>`; `cs config reset` restores defaults.

## Environment variables

| Variable | Effect |
|----------|--------|
| `CLAUDE_STATUSBAR_STYLE=capsule` | Render with this style (overrides config file) |
| `CLAUDE_STATUSBAR_THEME=twilight` | Render with this theme (overrides config file) |
| `CLAUDE_STATUSBAR_NO_UPDATE=1` | Disable automatic update checks |
| `CLAUDE_STATUSBAR_WARNING_THRESHOLD=40` | Switch from green to yellow at 40% |
| `CLAUDE_STATUSBAR_CRITICAL_THRESHOLD=85` | Switch from yellow to red at 85% |
| `NO_COLOR=1` | Disable ANSI colors |

`CLAUDE_PLAN` is still accepted for legacy compatibility, but it no longer changes the rendered status line.

## JSON output

Use `--json-output` if you want a machine-readable payload instead of the formatted status line:

```bash
cs --json-output
```

## Usage cheatsheet

```bash
cs                              # render the status line (default command)
cs --style capsule              # render with a one-off style
cs --theme twilight             # render with a one-off theme

# Configuration
cs config show                  # show all persistent config
cs config set style hairline    # persist style → ~/.claude/claude-statusbar.json
cs config set theme linen       # persist theme
cs config set show_cost true    # session $ cost segment
cs config set show_cache_age false  # hide prompt-cache age segment
cs config set show_party false  # hide local AgentParty channel/unread line
cs config set show_tools true   # activity line: active tool + completed rollup
cs config set show_agents true  # bottom line(s): running subagents + elapsed
cs config set show_duration true # identity line: ⏱ session duration
cs config set show_lines false  # hide identity-line +added -removed (on by default)
cs config set show_version false  # hide the faint · vX.Y.Z (+ ↑update hint) at line end
cs config set show_mode false    # hide the ⚙ effort/thinking/fast/style line
cs config set mode_gradient false # mode line: plain per-tier colours, no gradient
cs config set show_ahead_behind true  # ↑2↓1 on the project/branch line
cs config set api_mode on        # force no-quota layout (relay/Bedrock/Vertex; default auto)
cs config set bar_shimmer true  # experimental: twinkling starfield on the battery bars
cs config set show_projection false  # hide the →NN% end-of-window projection
cs config set show_forecast false    # hide the ⚠~eta at-risk warning chip
cs config set show_todos false  # hide the todo-progress segment (on by default)
cs config reset                 # wipe config back to defaults

# Discovery
cs styles                       # list available styles
cs themes                       # list available themes
cs preview                      # render every style × theme with YOUR real data
cs preview --theme nord         # filter to one theme
cs preview --style hairline --theme dracula   # one specific combo

# Daemon mode (default since v3.6.0; v3.2 introduced it as opt-in)
cs --setup                      # default: writes `cs render` + starts daemon
cs --setup --inline             # opt out, use legacy inline path
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
