# Changelog

All notable changes to `claude-statusbar` are documented here. The format
loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
the project uses [Semantic Versioning](https://semver.org/).

For a quick overview of the latest release, see the
[GitHub releases page](https://github.com/leeguooooo/claude-code-usage-bar/releases).

---

## v3.13.7 — 2026-06-12

### Fixed
- **Parallel sessions logged into different Claude accounts no longer
  cross-contaminate the 5h/7d display.** The statusline stdin blob does not
  identify which account produced it, so with multiple accounts running
  side-by-side, ALL sessions wrote into the current login's shared store — and
  the "later resets_at wins" merge let another account's 7d window mask the
  real one with no heal path (live incident: bar showed the other account's
  7d 14% while `/usage` said 77%). A reading's identity is now
  `(window, resets_at)`: the shared store keeps per-reset buckets, each render
  is answered from the bucket matching its OWN blob's reset, and all
  v3.13.3–v3.13.5 healing rules (monotonic merge, confirmation grace,
  re-baseline acceptance) apply unchanged within a bucket. Legacy store
  schemas migrate automatically.
- **`→NN%` projections were artificially conservative during heavy use.**
  Three stacked causes: (1) the cross-account bug above also starved the real
  window's projection samples (samples for an earlier-reset window were
  rejected outright — the live window had 2 samples in 28h, leaving →NN% on
  cold priors); (2) a flat 20%/h plausibility cap silently rejected genuine
  heavy parallel-session burn (observed 37%/h on the 5h window), so the
  "recent rate" never existed exactly when it mattered — caps are per-window
  now (5h 60%/h, 7d 10%/h) with a ≥300s observation-span floor as the glitch
  filter; (3) the 7d projection ignored current momentum entirely — the rate
  measured over the last 3h now carries the next ≤3h (it can only raise the
  bucket estimate, never lower it).

### Changed
- **Battery bar fill is now a same-hue gradient.** The left cell anchors the
  exact severity colour (green/yellow/red semantics unchanged), fading darker
  toward the progress tip by scaling toward black — hue stays rich, the tip
  melts softly into the empty section, and a lone filled cell stays pure
  colour. Bar frame, ⏰, separators and all classic identity elements are
  untouched.

---

## v3.13.6 — 2026-06-11

### Fixed
- **Switching Claude accounts no longer keeps showing the previous account's
  5h/7d usage.** The shared stores (`rate_latest.json`, `rate_projection.json`)
  were account-global with no account key, so after `/login` to a different
  account the old account's reading stayed "plausible" for days and its later
  `resets_at` won every reconcile merge — the bar stayed pinned to the old
  account's percentages (and its learned `→NN%` projections) until the old
  window expired. Both stores are now keyed by the logged-in account
  (`oauthAccount.accountUuid` from `~/.claude.json`, memoized on file
  mtime/size — renders normally pay only a `stat()`): each account gets its own
  `rate_latest.<uuid>.json` / `rate_projection.<uuid>.json`, switching back
  restores that account's own data, and when the account can't be detected
  (API-key/headless setups) the legacy unsuffixed paths keep working unchanged.

---

## v3.13.5 — 2026-06-10

### Fixed
- **The `→NN%` projection relearns after an official re-baseline instead of
  freezing for the rest of the window.** The sample recorder refused any
  same-window reading at or below the recorded max — meant to filter stale
  session replays, but those are already gated upstream by the reconcile merge
  (v3.13.3/v3.13.4). After Anthropic re-baselined the weekly limit (19% → 3%),
  no new sample could be recorded until usage exceeded the old 19%, so the
  projection kept showing a pre-rebaseline `→100%` for days. A converged
  reading below the same-reset max now means the limit changed: all stored
  samples for that window are in old-denominator units and incomparable, so
  they're dropped, display smoothing restarts, and the projection relearns
  from the window's bucket priors onward.

---

## v3.13.4 — 2026-06-10

### Fixed
- **Idle Claude Code windows can no longer pin the 5h/7d bars to hours-old
  readings.** An open-but-idle window replays its last `rate_limits` blob on
  every statusline render. If that blob's `five_hour` `resets_at` is already in
  the past, the whole blob is hours old (a fresh API response always carries a
  future 5h reset) — yet its `seven_day` value still looked plausible and kept
  "re-confirming" the shared store, defeating v3.13.3's 120s re-baseline grace
  (observed live: frozen sessions replaying 7d=15% blocked the official 3%
  indefinitely). Blob freshness is now judged as a whole: a blob with any
  implausible window reset neither overwrites the shared reading nor restarts
  the grace clock.

---

## v3.13.3 — 2026-06-10

### Fixed
- **5h/7d bars no longer stick at a stale high % when Anthropic re-baselines
  usage mid-window.** When account limits change (e.g. the weekly limit is
  raised), the official `used_percentage` can drop within the same window —
  observed live: `/usage` said 3% while the bar was pinned at 19% (and would
  have stayed there until the weekly reset). The cross-session merge assumed
  "within a window, used% only grows" absolutely; it now tracks when the stored
  reading was last confirmed by any live session (`observed_at` in
  `rate_latest.json`) and accepts an official downward revision once the old
  value has gone unconfirmed for 120s. Stale idle-session replays still can't
  drag the bar down — any session that still sees the higher value re-confirms
  it every render and keeps the grace clock ticking. Pre-existing stores
  without `observed_at` heal on the first render after upgrading.

---

## v3.13.2 — 2026-06-09

### Changed
- **Effort gradient reworked to match Claude Code's own effort ladder.** A vivid
  monotonic cool→purple spectrum — low/auto teal · medium azure · high blue ·
  xhigh indigo · max violet · **ultracode** magenta — with each tier sweeping
  toward the next hue so it reads as a real gradient (not a flat block) and the
  level is obvious. (The old rainbow made coral `max` look "hotter" than
  `ultracode`, inverting the order.)
- **`ultracode` is shown as `ultracode(+workflows)`** to spell out what it means
  (Claude Code: `ultracode = xhigh + workflows`).

---

## v3.13.1 — 2026-06-07

### Fixed
- **The `→NN%` projection no longer vanishes near a reset.** v3.12.1 hid the
  projection when it rounded to the current usage (to avoid a redundant-looking
  `→47%` next to `47%`), but that made it disappear entirely on a window that's
  nearly reset or flat. It's now always shown — `→47%` next to `47%` is honest
  ("you'll end about here"), not broken.

---

## v3.13.0 — 2026-06-07

### Added
- **Session-mode line (`show_mode`, default on).** A dedicated `⚙` line shows
  how the current turn is configured — `⚙ effort:high · think:on · fast:off ·
  style:default` — read straight from Claude Code's stdin (`effort.level`,
  `thinking.enabled`, `fast_mode`, `output_style`). Each field is dropped when
  absent. `cs config set show_mode false` to hide.
- **Per-effort gradient (`mode_gradient`, default on).** The whole mode line is
  tinted with a static gradient whose palette depends on the effort tier — a
  cool→hot ladder so the level is obvious at a glance: low/auto slate, medium
  blue, high cyan, xhigh amber, max coral, ultracode pink→purple. Static, not
  animated: an external statusLine is re-invoked at ≤1 Hz, so motion can only
  flicker — a stable per-tier sweep is the clean result. `cs config set
  mode_gradient false` falls back to plain per-tier text colours.

### Fixed
- **Reconcile rejects implausible reset times.** A bogus far-future `resets_at`
  (e.g. from corrupt/odd input) used to poison the account-global reconcile
  store permanently — "later reset wins" meant the real, smaller reset could
  never replace it, showing absurd timers like `⏰2283122h`. Reconcile now
  ignores resets beyond a window-length-plus-slack and lets a plausible reading
  replace a poisoned one (self-healing).

---

## v3.12.1 — 2026-06-07

### Fixed
- **Projection no longer echoes the current usage.** The `→NN%` projection is
  floored at current usage, so when it predicted no visible growth it would
  render right next to an identical number (`1% … →1%`) and read as a broken
  chip. It's now shown only when it forecasts a higher whole percentage;
  otherwise it's hidden (e.g. near a reset, or while usage is flat).
- Release guard: `pyproject.toml`, `.claude-plugin/marketplace.json`, and
  `.claude-plugin/plugin.json` versions are now kept in lock-step (a test fails
  the build if they drift) — the marketplace had silently lagged at 3.10.0.

---

## v3.12.0 — 2026-06-05

### Added
- **Version on the bar (`show_version`, default on).** A faint `· vX.Y.Z` at the
  very end of the identity line — rendered in the darkest grey + a dim attribute
  so it's there when you look but never competes for attention. (Terminals can't
  shrink the font, so "faint" is how it stays unobtrusive.) Disable with
  `cs config set show_version false`.
- **Update hint.** When a newer version is on PyPI, an amber `↑<newver>` appears
  right after the version (e.g. `· v3.11.2 ↑3.12.0`). The background update check
  caches the latest version locally; the render path only reads that cache (no
  network, no per-second cost) and shows the arrow when newer — and stays silent
  if the cached check is stale.

---

## v3.11.2 — 2026-06-05

### Changed
- **`show_lines` is now on by default.** The identity line shows Claude Code's
  session lines-changed tally (`+182 -47`, +green/−red) out of the box. Disable
  with `cs config set show_lines false`.
- **Changelog is easier to find.** The PyPI project page now links the changelog
  and releases directly (project URLs), so you can see what changed without
  digging through the repo.

---

## v3.11.1 — 2026-06-04

### Fixed
- **Projection learning data is now kept clean.** The `→NN%` learner could be
  polluted by stale/odd samples; hardened so it learns only trustworthy slopes:
  - projections now reconcile against the account-global latest reading first,
    so an old Claude window can't write an expired low percentage into history;
  - within a reset window only increasing usage change-points are kept (no
    per-render duplicates), and bucket-rate learning ignores duplicate,
    decreasing, and cross-reset samples — killing the false high slopes that the
    coarse integer `used_pct` steps used to create;
  - a window is only recorded as "closed" when its reset time moves *forward*, so
    an old session bouncing backwards no longer looks like a new window.
- **The bar itself now reconciles too.** The `5h/7d` percentage and reset timers
  use the same account-global reconciled reading as the projection/forecast, so
  all open windows show consistent numbers (previously only the projection did).

### Changed
- **Per-tick projection cache.** Projection results are memoized for ~1s keyed on
  the reconciled reading, and history is compressed + bounded on load, so the
  render path doesn't recompute the learned model every tick.

---

## v3.11.0 — 2026-06-02

### Added
- **Always-visible rate-limit projections (`show_projection`, default on).**
  The 5h/7d windows now show `→NN%` estimates for expected end-of-window usage.
  The model records local samples, learns coarse usage rhythm, smooths by sample
  time instead of render frequency, and keeps a bounded error log for future
  tuning. Disable with `cs config set show_projection false`.
- **Separate imminent ETA warning (`show_forecast`, default on).** `show_forecast`
  now controls only the `⚠~ETA` chip, which appears after the projection when a
  window is projected to hit 100% before reset and the cap is imminent.

### Fixed
- **`context_window.used_percentage = null` handled as unknown.** Claude
  sometimes sends `null`; rendering now treats it as unknown (context tokens
  fall back to input+output token totals) instead of dropping into the
  expensive claude-monitor reset-time fallback path.

### Changed
- **Daemon renders only active windows.** `_active_sessions()` now uses a 10s
  freshness window (sorted freshest-first) rather than the 24h GC threshold, so
  stopped Claude windows keep their dirs for GC but leave the 1Hz work set. The
  thin client only signals an "outdated daemon" when the daemon genuinely
  predates the installed package code — not on ordinary age-stale output (which
  was letting a slow shared daemon get killed by sessions it hadn't reached).

---

## v3.10.0 — 2026-06-02

### Added
- **Live-activity line (3rd line).** An opt-in third status line surfaces what
  Claude is doing *right now*, parsed from the transcript via the same bounded
  reverse-tail read (≤320 KB) the cache countdown already uses:
  - **Todos** `▸ <in-progress task> (3/7)` — from the newest `TodoWrite` (full
    list, last-write-wins). On by default (`show_todos`); it's the clearest
    "is my long turn making progress?" signal.
  - **Active tool** `◐ Edit auth.py` (newest tool_use with no result yet). MCP
    names shortened (`mcp__figma__get_screenshot` → `get_screenshot`). Opt-in
    (`show_tools`). A separate completed-tool rollup `✓ Edit×14 Bash×6` is
    available via `show_tool_rollup` (a volume tally; default off).
  The line is style-agnostic (renders the same under classic / capsule /
  hairline) and is omitted entirely when nothing is active. The curated
  main line is untouched.
- **Identity line gains opt-in session context.** Next to `⤷ project ⎇ branch`:
  - **git ahead/behind** `↑2↓1` (`show_ahead_behind`) — reuses the dirty-state
    `git status --branch` call, no extra spawn; arrows only for nonzero
    directions.
  - **session duration** `⏱ 12m` (`show_duration`) and **lines changed**
    `+182 -47` (`show_lines`, +green/−red) — straight from stdin. These are
    Claude Code's own cumulative session tally, not a git diff.
- **Running subagents** — one **bottom line per agent** `◐ explore[haiku]
  <task> 2m15s` (`show_agents`, opt-in, **default off**). Background agents are
  detected as running until their queue-operation task-notification (their
  immediate launch-ack tool_result does *not* count as completion). Off by
  default because Claude Code already shows background agents in its own
  native panel, so enabling this largely duplicates it.
- **`.claude-plugin/marketplace.json`** — the repo is now a self-hosted plugin
  marketplace: `/plugin marketplace add leeguooooo/claude-code-usage-bar` then
  `/plugin install claude-statusbar`. (The render engine is still the `cs` CLI
  from PyPI.)
- **`bar_shimmer` (experimental, opt-in, default off, classic only)** — a faint
  twinkling starfield in the *empty* portion of the 5h/7d battery bars: a static
  high/mid/low dot field with bright stars (`✦`/`✧`) winking in and out. The
  fill color is never changed. Capped at the statusLine's ~1Hz refresh, so it's
  a gentle twinkle, not a smooth animation. `cs config set bar_shimmer true`.
- **Local worktree detection** — the identity line shows a bare `[worktree]`
  marker when the checkout is a linked git worktree (detected from `.git`
  pointing under `worktrees/`), independent of whether Claude Code passes the
  hint.

### Changed
- **One transcript scan, not two.** The cache countdown and the activity line
  now share a single bounded reverse-tail read (`read_activity` also returns
  `cache_age_seconds`/`cache_ttl`). Also makes the cache countdown
  **per-session-correct** — it reads the session's own transcript instead of
  the shared top-level `last_stdin.json` (which is last-writer-wins across
  windows and could show another session's cache age).

### Fixed
- **Auto-update now actually runs in daemon mode, without blocking renders.**
  Previously the once-a-day check only fired on the rare inline-fallback path
  (the daemon suppresses it and `cs render` just cats a frame), and when it did
  fire it ran the upgrade *synchronously* (up to ~65s) in the triggering render.
  Now the check spawns a **detached** background upgrade (never blocks), and the
  **daemon** triggers it on its own 24h-throttled cadence. After a successful
  upgrade the package mtime changes and the daemon restarts onto new code via
  the existing code-drift detection.

### Robustness
- The activity scan is fully defensive against malformed transcript shapes
  (non-string `file_path`, non-dict tool `input`, non-string `timestamp`) and
  is wrapped so any scanner failure degrades to "no activity line" rather than
  blanking the whole status bar — the scan runs before `main()`'s try/except.

## v3.9.1 — 2026-05-29

### Changed
- **Cache countdown always shows seconds.** The adaptive granularity that
  collapsed the 5min–1h band to a bare `Xm` (and the hour band to `Xh`/`XhYm`)
  is gone. The countdown now always renders the seconds field — `58m23s`,
  `1h59m03s`, `47s` — so it visibly ticks every render. A static `58m` read
  as frozen; a ticking `58m23s` makes it obvious the widget is live and the
  number is real. This pairs with v3.9.0's TTL auto-detect: subscription
  users now sit in the 5min–1h band most of the time, which previously showed
  no motion at all. Severity colors are unchanged — anything ≥1min keeps its
  `m`/`h` glyph → green; sub-minute stays bare seconds → yellow.

## v3.9.0 — 2026-05-29

### Changed
- **Cache countdown auto-detects the TTL.** The `cache 4m23s` countdown no
  longer trusts a fixed config value for the prompt-cache TTL. It now reads
  the ground truth Anthropic reports on every turn —
  `message.usage.cache_creation` buckets cache-write tokens by TTL, so a
  nonzero `ephemeral_1h_input_tokens` means a 1-hour `cache_control` ttl and
  `ephemeral_5m_input_tokens` means 5 minutes. This fixes a systematic
  ~55-minute early `cache COLD` for **Claude subscription (Pro/Max)** users:
  on a subscription, Claude Code requests the 1-hour TTL automatically, but
  the bar was hard-coded to 5 minutes. The detected value already reflects
  subscription-vs-API-key auth, `ENABLE_PROMPT_CACHING_1H`,
  `FORCE_PROMPT_CACHING_5M`, and the over-quota → 5m downgrade, so no static
  config could match it. Detection shares the existing reverse-tail read of
  the transcript (one pass, still capped at 320 KB), pulling age and TTL
  together; a final read-only turn (both buckets 0) keeps its age but falls
  through to the last turn that actually wrote cache. When no write signal
  exists (caching disabled / ancient transcript) it falls back to a
  conservative 300 s — early COLD beats claiming a dead cache is warm.

### Deprecated
- **`cache_ttl_seconds` config.** No longer consulted for rendering (the TTL
  is auto-detected). The key stays parseable and `cs config set
  cache_ttl_seconds …` still succeeds so existing configs don't break, but it
  has no effect.

## v3.8.1 — 2026-05-21

### Fixed
- **Outdated daemon after PyPI upgrade.** Long-lived daemon kept serving
  stale renders because its `rendered.meta.json` was fresh by the 5 s
  age check and lazy-spawn refused to restart over a live pidfile. Now
  the daemon writes `daemon_started_at` into meta, and the thin client
  compares it against the installed package's newest `.py` mtime — if
  disk is newer than the running daemon, the meta is treated as stale,
  the old daemon gets `SIGTERM`, and `_spawn_daemon_async` brings up a
  fresh process on the next tick. Pre-3.8.1 daemons (without the new
  field) keep the old age-only behavior for smooth rollout.

## v3.8.0 — 2026-05-21

### Added
- **Project + branch identity segment (default on).** Renders a second
  line `⤷ <project> ⎇ <branch>●` below the existing status bar. Project
  name is read from Claude Code's `workspace.repo.name` stdin field
  (falls back to cwd basename); branch comes from `.git/HEAD` directly
  (no `git` fork on the render hot path); the `●` dirty marker is
  refreshed in the background by a detached
  `python -m claude_statusbar._git_refresh` helper and cached for 5 s,
  so the inline render stays well under its 30 ms budget. Daemon mode
  exposes the same helper for in-thread cache warming. Outside a git
  repo the line collapses to `⤷ <project> (no git)`. Disable with
  `cs config set show_project_branch false`.

---

## v3.7.0 — 2026-05-15

### Added
- **`cs --setup --project [PATH]`** — write a project-level
  `.claude/settings.json` (PATH defaults to the current directory) that
  overrides the global statusLine. Use this when another tool keeps
  reclaiming the user-level slot — the project file wins for any Claude
  Code session opened in that directory. Preserves other keys (hooks,
  permissions, etc.); refuses to trample a non-cs `statusLine` already
  present. Honors `--inline`.
- **Displacement warning on the bar.** If `~/.claude/settings.json`
  `statusLine.command` no longer resolves to one of our binaries (`cs` /
  `cstatus` / `claude-statusbar`), `cs render` appends a short red
  `⚠ statusLine 被 <foreign> 占用 · cs --setup` suffix to the bar line.
  Fires in both the fast (daemon-cat) path and the inline fallback —
  useful when a project keeps `cs` alive via the new `--project` override
  but the global file got hijacked. You see it the moment the bar renders.

### Fixed
- `ensure_project_statusline_configured` refuses to overwrite a
  `.claude/settings.json` that exists but can't be read (e.g. permission
  denied). Previously the read error was swallowed and treated as
  "empty," which would have silently clobbered the file on the next write.
- Clean error messages when `.claude` exists as a regular file (instead
  of a directory) or when the project path can't be resolved (symlink
  loop, unresolvable `~`). No more raw `NotADirectoryError` traceback.
- `cs --project` without `--setup` is now rejected by argparse; the flag
  used to be silently swallowed and the bar would render normally.

---

## v3.6.0 — 2026-05-08

### Changed
- **`cs --setup` defaults to daemon (fast) mode.** Previously you had to remember
  `--fast` to get the long-lived daemon + `cs render` thin client; the bare
  `cs --setup` wrote inline mode at refreshInterval=1, which costs ~3% CPU
  continuously. Daemon mode keeps it under 1% with smoother per-second ticks.
  Existing users running `cs --setup` after upgrading will be auto-bumped from
  inline to daemon. To opt out, run `cs --setup --inline`. The legacy `--fast`
  flag still works (no-op now). Daily auto-repair (background) preserves the
  user's existing fast/inline choice — it doesn't reach into your settings to
  change policy on you.

### Fixed
- **`cs --setup --inline` now actually downgrades.** In 3.5.x, passing `fast=False`
  to `ensure_statusline_configured` quietly preserved an existing fast-mode
  config (the OR-with-existing logic was meant for the auto-repair path but
  blocked explicit user requests). The function is now tri-state:
  `fast=None` preserves existing (auto-repair); `fast=True/False` is an
  explicit user request and is respected.
- **Python 3.9 compatibility.** `updater.py` and `cli.py` used PEP-604 union
  syntax (`X | None`) at runtime, which 3.9 doesn't support. Added
  `from __future__ import annotations` so all annotations are lazy strings.
  CI on 3.9 was failing in 3.5.x — verified now passing on 3.9–3.12.

### Added
- GitHub Actions CI: pytest matrix on Python 3.9–3.12, ruff lint job,
  cancel-in-progress concurrency, `contents: read` permissions only.
- `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1).
- Animated hero GIF at `docs/images/hero.gif` (driven by `scripts/hero.tape`,
  rebuilt via `bash scripts/build-hero-gif.sh`).
- Issue & PR templates under `.github/`.

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
