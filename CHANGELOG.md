# Changelog

All notable changes to `claude-statusbar` are documented here. The format
loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
the project uses [Semantic Versioning](https://semver.org/).

For a quick overview of the latest release, see the
[GitHub releases page](https://github.com/leeguooooo/claude-code-usage-bar/releases).

---

## v3.5.1 — 2026-05-08

### Changed
- **`show_cache_age` default flipped to `True`** — the cache-expiry countdown
  is one of the v3.2 highlights and friendlier as opt-out than opt-in. Users
  who explicitly set `show_cache_age: false` are unaffected; the new default
  only applies when the field is missing from `~/.claude/claude-statusbar.json`.

### Documentation
- README documents `npx skills add leeguooooo/claude-code-usage-bar -g -y` as
  an installable path for users who already have the `cs` binary and want only
  the conversational skill. The skill repo structure (`skills/<name>/SKILL.md`)
  is recognized by `npx skills` out of the box.

## v3.5.0 — 2026-05-08

### Added
- **Consolidated `claude-statusbar` skill.** One Claude Code skill that handles
  all `cs` operations conversationally. Say "switch theme to nord" /
  "余量颜色改成 #4ec85b" / "diagnose why my bar isn't showing" and it routes
  to the right `cs` command. Auto-installed alongside slash commands by
  `cs --setup`; standalone install via `cs install-skill` or
  `npx skills add leeguooooo/claude-code-usage-bar`. Old slash commands
  (`/statusbar`, `/statusbar-theme`, etc.) still work.
- New `cs install-skill` subcommand for skill-only installs (mirrors the
  semantics of `cs install-commands`: idempotent, `--force` to overwrite user
  edits).

### Plumbing
- `pyproject.toml` package-data now includes `skills/**/*.md`; the skill
  source ships at `skills/claude-statusbar/SKILL.md` (top-level for
  visibility) and is mirrored to `src/claude_statusbar/skills/...` for wheel
  packaging — same pattern as the existing `commands/` directory.

## v3.4.1 — 2026-05-07

### Added
- **Per-severity color overrides.** `cs config set color_ok "#4ec85b"` (and
  `color_warn` / `color_hot`) layers your own RGB on top of any theme without
  touching the theme's other fields. Empty string clears the override; accepts
  `#rgb`, `#rrggbb`, with or without the leading `#`. Useful when you like a
  theme's overall feel but want a sharper "calm" green or a softer warning
  color.

### Fixed (codex post-release review)
- README themes table now lists all 9 themes (`catppuccin-mocha` and
  `tokyo-night` were missing from the configuration row).
- `tests/test_config.py` parametrize covers the two new themes.
- `.claude-plugin/plugin.json` description bumped from a `v3.2` blurb to one
  that reflects v3.4 features.

## v3.4.0 — 2026-05-07

### Added
- **Per-segment color management.** Before, when `7d` hit warning the entire
  line tinted yellow (5h label, separators, model, all sharing a single
  `overall_color = max(severity)`). Now each numeric segment colors itself by
  its own pct: 5h sees only `msgs_pct`, 7d sees only `weekly_pct`, the
  model+context block sees `ctx_used_pct`, cache keeps its own string-age
  severity. No color leaks across segments.
- **Classic style now respects themes.** `progress.py` previously used raw
  8-color ANSI (`\033[32/33/31m`) regardless of theme. Switching theme had
  zero effect on classic. Now classic pulls from
  `theme.s_ok / s_warn / s_hot`, so all 9 themes finally apply to it.
- **Hierarchy via mute.** `[ ]` brackets, `(used/size)` parens, and the
  ` | ` separator move to `theme.mute` so the bright severity colors only
  paint actual data. Numbers and time stay the visual focus.
- **Two new themes.** `catppuccin-mocha` (community-favorite pastel, easy on
  long viewing) and `tokyo-night` (deeper neon-blue mood with restrained
  accents). Both honor the per-segment severity contract.
- **`theme.pill_cost` field.** Capsule's `$` cost pill stops sharing
  `pill_lang` with the language pill (a longstanding color collision). New
  mandatory field on every theme; existing fields unchanged.
- **`ctx_pct` plumbed through.** `core.py` now computes a nullable
  `Optional[float]` from `context_window_size > 0` (not falsy
  `raw_pct == 0`, which would conflate genuine 0% with "no context info").
  All three styles consume it; capsule gains a model-pill severity dot,
  hairline colors the model text.

Visual identity unchanged: battery bar with overlaid percentage, `[ ]`
brackets, `🕐` / `⏰` clock emojis, and ` | ` separators all kept. This is a
palette + scoping refinement, not a redesign.

## v3.2 (cumulative through v3.3.4)

### Added
- **Daemon fast-mode.** `cs --setup --fast` swaps the statusLine command to
  `cs render` backed by a long-lived `cs daemon`. At `refreshInterval: 1` this
  cuts continuous CPU from ~6% to ~2%, render wall-clock from ~60ms to ~5ms.
  Crash-safe (auto-falls-back to inline render if the daemon dies;
  lazy-respawns).
- **OS-managed daemon.** `cs daemon install` installs a launchd agent (macOS)
  or systemd user unit (Linux) so the daemon auto-starts on login and is
  restarted on crash by the OS.
- **`cache 4m23s` countdown.** Counts down to Anthropic's prompt-cache expiry
  (default 5min TTL); flips through green → yellow (<1min) → red `cache COLD`.
  Configurable TTL via `cs config set cache_ttl_seconds 3600` for users on the
  1-hour extended cache. **For Pro/Max subscribers**, cache hits consume ~10×
  less of your 5h / 7d rate-limit quota — letting it go COLD costs you ~10×
  more quota on the next prompt. The widget tells you whether to send now or
  wrap up first.
- **`cs doctor` 1Hz hint.** Detects `refreshInterval ≤ 2s` with the inline
  command and recommends `cs --setup --fast`.
- **Import-shaving on the inline path.** Even users who don't opt into daemon
  mode get ~30% faster renders.
- **Per-session daemon state (v3.3.0).** Each Claude Code `session_id` routes
  to `~/.cache/claude-statusbar/sessions/<sid>/`, fixing a multi-window race
  where two sessions could write the same render file.
- **`cs preview --theme` / `--style` filter (v3.3.2).**
- **Adaptive cache granularity (v3.3.2).**
- **Codex review follow-ups (v3.3.3, v3.3.4).**

Daemon mode remains opt-in.
