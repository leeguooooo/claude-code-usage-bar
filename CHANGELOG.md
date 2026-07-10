# Changelog

All notable changes to `claude-statusbar` are documented here. The format
loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
the project uses [Semantic Versioning](https://semver.org/).

For a quick overview of the latest release, see the
[GitHub releases page](https://github.com/leeguooooo/claude-code-usage-bar/releases).

---

## v3.29.6 — 2026-07-10

### Documentation

- **Clarified Claude Code vs Codex support.** The README now has an explicit
  support matrix: Claude Code remains the full native `statusLine` integration
  for quota/session/context/cache/activity data, while Codex support is the
  local AgentParty bridge that shows channel, identity, listener state, unread
  count, and last-message preview from
  `~/.agentparty/state/<workspaceId>/statusline.json`.
- **Updated the latest-release summary.** The top of the README now points to
  v3.29.6 and summarizes the v3.29.5 daemon/session fixes instead of leaving an
  older v3.28.x entry first.

## v3.29.6 — 2026-07-10

### A maxed projection now says WHEN the quota runs out

`→100%` alone buried the useful half of the prediction. When the pace
overshoots the cap, the chip now carries the estimated time until usage
actually hits 100%: `5h[▓ 27%] 🕐4h19m →100%·1h12m` reads "headed to the cap,
empty in about an hour". Computed from the same blended-rate projection
(unclamped twin), only shown when depletion lands before the window reset.

### Quiet channels no longer read as "listener down"

AgentParty CLIs older than 0.2.80 heartbeat only when traffic arrives, so a
listener on a quiet channel went heartbeat-stale after 10 minutes and the bar
showed `⊘ listener down` while the process sat healthily connected (seen live:
a serve alive with a 32-minute-old heartbeat). The process is the better
witness: alive and verifiably a `party` process → `◉ watching/serving`,
whatever the heartbeat age. A recycled PID (alive but not a party process)
still reads as down. Upstream, AgentParty 0.2.83 also heartbeats on a 60s
timer and an exiting `watch --once` no longer wipes another live listener's
record.

---

## v3.29.5 — 2026-07-09

### launchd/systemd daemons were unkillable — and immune to upgrades

`_process_is_our_daemon` matched the module path `claude_statusbar`
(underscore), which only appears in lazy-spawned daemons
(`python -m claude_statusbar.cli …`). A service-managed daemon's cmdline is
`<venv python3> /path/to/cs daemon _run` — no underscore form anywhere. So for
every launchd/systemd instance:

- `cs daemon stop` refused with a false "PID reused. Refusing to SIGTERM".
- The upgrade drift-kill (guarded since v3.29.1) also refused — the stale
  daemon kept serving old code after every upgrade.

The matcher now recognizes all spawn shapes, keyed on the shared
`daemon _run` invocation.

### The AgentParty line showed in sessions that never joined

The AgentParty cache is cwd-scoped by contract, but Claude Code sessions are
not: several windows share one project directory and only some of them join a
channel (typically with a per-session `AGENTPARTY_CONFIG`). Every window in
the directory rendered whichever session's channel/identity wrote the cache
last — dead listeners and all.

The env var never reaches the Claude Code process (agents export it inside
individual Bash calls), so the line is now gated on the only session-scoped
evidence there is: the session's own transcript. A window shows the party
block only after its transcript contains a party command
(`party init/send/watch/…` or `AGENTPARTY_CONFIG`). Scans are incremental
(byte offset per session, sticky verdict), so a large transcript is read once
and each later render reads only the appended tail. Sessions without a
transcript (preview, tests, bare `cs`) keep the old always-show behavior.

### An exiting daemon could delete the current owner's pidfile

`flock` locks an inode, not a path: after an unlink+recreate cycle, two daemons
each hold "the" lock on different inodes. `_release_pidfile` unlinked by path
unconditionally, so the exiting daemon deleted the pidfile the *current* owner
had just written — making it invisible to stop/status/spawn_if_dead, so the
next render spawned a duplicate. Observed live twice in one day (a pidfile-less
daemon looping for 15+ minutes beside a fresh one). Release now unlinks the
locked file only while it still points at the exiting daemon's own inode.

---

## v3.29.4 — 2026-07-09

### The daemon's auto-upgrade silently failed under launchd/systemd

launchd and systemd run the daemon with the bare system PATH, which lacks
`~/.local/bin` — where uv and pipx actually live. `shutil.which("uv")` failed
there, so the upgrade fell through to `python -m pip install --upgrade` — and a
uv tool venv ships **without pip**. Net effect: for uv installs whose daemon
runs as an OS service, the daily auto-upgrade has never worked. Tool discovery
now searches well-known directories (`~/.local/bin`, `~/.cargo/bin`, Homebrew)
after PATH.

### `cs upgrade` is now the one documented upgrade path

Users kept being told (by READMEs and by agents guessing) to run
`uv tool install …` — and many of them don't have uv, because they installed
via pip. `cs upgrade` has picked the right channel since 3.28.1; now every
surface says so: the README's Upgrading section, the claude-statusbar skill's
decision tree (with an explicit "never guess a package-manager command" note),
its trigger words (`upgrade`/`update`/`升级`), and `/statusbar-doctor`'s
follow-up suggestions.

---

## v3.29.3 — 2026-07-09

### The systemd unit had the same respawn loop v3.29.2 fixed on launchd

v3.29.2 changed the launchd plist to `KeepAlive: {SuccessfulExit: false}` but
left the systemd user unit at `Restart=always` — which relaunches even a clean
exit. On Linux, whenever a lazy-spawned daemon held the pidfile, systemd's own
instance exited 0 and was rerun every `RestartSec=5`, forever (and v3.29.2's
exit-0 change made the loop *silent*). `cs daemon stop` also never stuck: clean
exit, immediate relaunch. Now `Restart=on-failure` — crashes still bounce.
Linux installs need `cs daemon install` re-run.

### `mentions_only` now comes from the AgentParty contract, not `ps`

AgentParty 0.2.79 writes `listener.mentions_only` into `statusline.json`
(contract change shipped alongside this release). The statusbar reads it
verbatim; the `ps` argv probe remains only as a fallback for older CLIs. This
removes the last per-render fork on up-to-date installs and closes the
pid-recycling staleness the memoised probe could serve.

---

## v3.29.2 — 2026-07-09

### launchd was respawning a redundant daemon every 10 seconds

The LaunchAgent shipped `KeepAlive: true`, which restarts the job on *any*
exit. Whenever the thin client's lazy-spawn already owned the pidfile,
launchd's own `cs daemon _run` found it taken, printed `daemon already
running`, exited 1, and was relaunched `ThrottleInterval` seconds later —
forever. A live `daemon.stderr.log` had **47429** such lines.

`run_forever` now exits **0** when another daemon holds the pidfile (a daemon
is running; this process's purpose is served), and the plist uses
`KeepAlive: {SuccessfulExit: false}` so a clean exit ends the respawn while a
real crash still bounces the daemon.

Existing installs need `cs daemon install` re-run to pick up the new plist.

### The test suite was writing into the user's real daemon log

`test_render_payload_signal_alarm_aborts_slow_render` sets `RENDER_TIMEOUT_S`
to 1 and lets a render time out, but `_log()` writes to the real
`~/.cache/claude-statusbar/daemon.log`. Every `pytest` run appended a
`render timed out after 1s` line there; **260** had accumulated, and they
masked the daemon's genuine timeouts (logged as `after 12s`, none since
2026-06-03). Diagnosing a "slow render" from that log meant reading test
output as production signal. The test now stubs `_log`.

### Warm renders are ~2.5x faster

v3.29.0's `--mentions-only` probe forked `ps` on **every** render — about 4ms
of a 6ms warm render. A process's argv never changes, so it is memoised per
pid. Warm render: ~6.1ms → ~2.4ms.

---

## v3.29.1 — 2026-07-09

### The daemon was crash-looping on slow renders

`run_forever`'s sleep loop read the clock twice:

```python
end = time.time() + sleep_for
while _running and time.time() < end:
    time.sleep(min(0.2, end - time.time()))   # <- second read
```

If the process was descheduled between the guard and the subtraction, the
remainder had already elapsed, `time.sleep()` got a negative number and raised
`ValueError: sleep length must be non-negative`. The daemon died. Any render
slower than the tick interval — the `render timed out after 1s` lines in
`daemon.log` — made the window wide enough to hit routinely.

This is the root cause behind v3.29.0's third fix. The orphan-`.tmp` sweep and
the auto-update check were not merely starved by sharing a 30-minute timer; the
daemon was being killed long before it could reach 30 minutes, then restarted by
launchd. The remainder is now clamped at zero.

---

## v3.29.0 — 2026-07-09

### AgentParty block redesign

The AgentParty line answered none of the questions it existed to answer.

- **`watch down` was a lie.** The statusline contract writes the listener
  heartbeat as `heartbeat_ts`; `party.py` read `heartbeat_at`. It always got
  `None`, so the heartbeat never looked fresh and *every live listener rendered
  as `down`*. Two test fixtures wrote `heartbeat_at` too, so the bug was pinned
  in place by its own tests.
- **It was unreadable.** The whole line stacked the `FAINT` attribute on top of
  the theme's dimmest grey. Colour is now assigned by meaning: channel in `ink`,
  identity in `mute`, listening state green/red/grey, unread count amber.
- **The message no longer crowds the header.** It gets its own line, clipped to
  54 display columns with wide CJK glyphs counted as two, so a long preview
  cannot push the header off screen.
- **The listening state is stated outright** — `◉ watching` / `◉ serving`
  (green), `⊘ listener down` (red), `◌ not listening` (grey, no listener
  attached). `@mentions` is appended when the live listener runs with
  `--mentions-only`, detected from its argv.
- **The message carries its own state**: `●` unread / `○` read, followed by `@`
  when the preview mentions your identity. Mention matching is exact, so
  `@leo-zego-im` does not mark `leo-zego`. (The writer clips previews at 48
  chars, so a mention past that cut is missed — it under-reports, never
  over-reports.)
- Emoji gave way to monochrome geometry (`⬡` agent, `⬢` human). Glyphs now
  inherit the theme colour and hold a single column.

### Daemon restart fixes

Found while investigating "I upgraded but nothing changed".

- **The code-drift tick burned its own spawn debounce.** On detecting drift the
  thin client SIGTERMed the old daemon and immediately called
  `_spawn_daemon_async()`. The old daemon was still alive handling the signal,
  so `spawn_if_dead` found a valid pidfile and refused — after the 30s debounce
  marker had already been stamped. Every session then inline-rendered for 30
  seconds. The drift tick no longer spawns; the next tick (~1s) does.
- **`_signal_outdated_daemon` could SIGTERM an unrelated process.** A session's
  meta outlives the daemon that wrote it, so `meta["pid"]` may have been
  recycled. It now verifies `_process_is_our_daemon(pid)` first — the guard that
  the function's own docstring already claimed to apply.
- **The orphan-`.tmp` sweep and the auto-update check were starved.** Both hung
  off the session-GC timer, which is seeded to daemon start and fires after 30
  minutes. Since the thin client restarts the daemon on every code drift, it
  rarely lived that long and neither ever ran. Observed live: 15 orphaned `.tmp`
  files, the oldest 99 minutes old, against a 60-minute cutoff. Maintenance now
  runs on the first tick; session GC keeps its deferral.

---

## v3.28.2 — 2026-07-09

### Fixed
- **`cs upgrade` detects uv-tool installs correctly.** uv tool environments
  symlink `bin/python3` to the shared uv Python install; the upgrade detector now
  checks the original executable path and environment prefix before falling back
  to the resolved Python path, so `cs upgrade` selects
  `uv tool install --upgrade claude-statusbar` instead of a non-working venv pip.

## v3.28.1 — 2026-07-09

### Added
- **Foreground upgrade command.** `cs upgrade` now upgrades the install channel
  that is actually running `cs` (`uv tool`, `pipx`, or plain `pip`), which avoids
  the confusing case where `pip install -U claude-statusbar` updates a different
  Python environment than the `cs` shim on `PATH`.
- **Version aliases.** `cs -v`, `cs -V`, and `cs -version` now behave like
  `cs --version`.

## v3.28.0 — 2026-07-09

### Added
- **AgentParty / Codex bridge line (`show_party`, default on).** When the same
  workspace has an AgentParty local status cache, the bar appends a local-only
  line such as `🎈 #agentparty · 🤖 xdream-agent · 👂serve · 3 unread · bob:
  shipped the auth patch 2m`. This is designed for Codex + AgentParty workflows:
  the writer side runs in AgentParty, while `cs` only reads
  `~/.agentparty/state/<workspaceId>/statusline.json`.
- **Shared workspace id contract.** The reader matches AgentParty's cwd-scoped
  `workspaceId` algorithm and has fixture tests for macOS `/tmp` behavior, so
  Codex/AgentParty and Claude Code renders point at the same local state file.

### Changed
- **Documentation now separates Claude Code and Codex support.** Claude Code
  remains the full native `statusLine` data source for quota/session fields;
  Codex support is the local AgentParty presence/channel/unread bridge and does
  not make network requests or read AgentParty tokens.

### Fixed
- **Stale listener state degrades visibly.** If the AgentParty cache is older
  than 10 minutes, or the recorded listener pid is gone, the appended line marks
  `stale` / `down` instead of showing a live listener.

## v3.27.0 — 2026-07-03

IP-risk detection re-synced with the ip-check.leeguoo.com service (this module
mirrors its `classify` + `claude-verdict`); both diverged and are now aligned.

### Added
- **China-cloud detection.** Claude account-risk systems flag Chinese clouds
  (Alibaba/Aliyun, Tencent/QCloud, Huawei, ByteDance/Volcengine, Baidu, UCloud,
  Kingsoft…) by provider **org/ASN**, not by where the IP geolocates — so a
  Chinese cloud's *US* node still counts. The local scorer now detects these by
  org keyword and ASN, adds a +25 risk weight on top of hosting (33 → 58, 中度;
  worse than a neutral AWS-US datacenter at 60), and exposes a `china_cloud`
  flag. A CN-registered but non-hosting org (a normal residential ISP) is *not*
  misclassified as a cloud. This is the most relevant signal for the tool's
  audience — users on a Chinese cloud's overseas node — which was previously
  scored as an ordinary datacenter and let through.

### Fixed
- **Ban-risk threshold aligned with the crit band.** `verdict()` treated
  `risk >= 67` as ban-risk while `classify()`'s crit band is `risk >= 70`, so
  scores 67–69 on a non-anonymizer type read as ban-risk in one place and only
  中度 in the other. Both now use 70 (matching the ip-check service fix).

## v3.26.0 — 2026-07-03

Community issue sweep — all four open issues fixed (#29 #30 #31 #32).

### Fixed
- **Windows: `cs doctor` / `cs --setup` false-positive "not ours" (#32).**
  `shutil.which("cs")` on Windows resolves to `cs.EXE`; the basename never
  exact-matched our command names, so setup refused to configure and doctor
  always flagged a foreign statusLine. Command basenames are now lowercased
  and stripped of the pip/pipx shim extensions (`.exe`/`.cmd`/`.bat`) before
  matching. Foreign tools ending in `.exe` are still refused.
- **Windows: unbounded daemon process leak (#31).** The old no-`fcntl`
  fallback always returned True ("honor system"), so every stale render tick
  spawned another daemon (~150 orphans/day reported). Three defenses now:
  a real `msvcrt.locking` exclusive lock on a separate `daemon.lock`
  sentinel (locking `daemon.pid` itself would blind `stop`/`status` —
  Windows byte locks are mandatory), a ctypes `OpenProcess` liveness probe
  (`os.kill(pid, 0)` on Windows *terminates* the target), and a 30s spawn
  debounce in the thin client so even a broken lock leaks at most one
  short-lived process per 30s. *Not yet verified on real Windows — feedback
  welcome on #31.*

### Added
- **`CLAUDE_CODE_AUTO_COMPACT_WINDOW` / `CLAUDE_CODE_DISABLE_1M_CONTEXT`
  respected for the ctx gauge (#29).** Users who raise the context window
  (e.g. `400000`) no longer see ctx% computed against the stock window;
  a truthy `CLAUDE_CODE_DISABLE_1M_CONTEXT` caps a >200K reported window
  back to 200K. Empty/invalid values keep current behavior.
- **`show_cwd` toggle (#30).** Opt-in working-directory segment (default
  off) rendered from stdin's `workspace.current_dir` — zero extra I/O.
  `cwd_style` chooses `basename` (default) or `full`; the segment is
  skipped when it would just repeat the project name.

## v3.18.0 — 2026-06-29

### Added
- **Stale-quota hint instead of silently blank 5h/7d bars.** When the statusLine
  pipeline stops feeding cs (another tool displaced the statusLine, or the daemon
  died) the cached 5h/7d windows expire and the expiry guard hid both bars —
  indistinguishable from a fresh session, so it just looked *broken*. The bar now
  shows `⟳ 5h/7d stale·restart` (yellow) in that exact case, telling you it's
  stale and a restart refreshes it. Gated tightly: only fires when the client
  emits rate_limits, an assistant turn already exists (a healthy session would
  have data by then), and the quota cache is genuinely all-expired — so a real
  session-start still shows the normal `--%` placeholders, never a false alarm.
- **`cs doctor` now reports 5h/7d quota-cache freshness** — `fresh` / `empty` /
  `stale (last update Nh ago … restart Claude Code; if it persists another tool
  took the statusLine → cs --setup)`. Turns the cache-file archaeology a user
  otherwise had to do into one diagnostic line.

## v3.17.0 — 2026-06-29

### Added
- **Balance fuel-gauge battery (`balance_bar`, default on).** The relay balance
  now renders as a battery bar — `bal[████ 52%] $26.00` — where the fill is the
  **remaining** proportion (a fuel/phone-battery mental model: full = green,
  getting low = yellow ≤25%, nearly empty = red ≤10%), with the remaining amount
  trailing. So you see both how much is left (the gauge + %) and the absolute
  figure at a glance. Falls back to the plain `bal $X` text when the relay
  reports no usable hard-limit (some relays return a sentinel/zero limit, which
  would make a gauge misleading). Turn the bar off with
  `cs config set balance_bar false` to keep the plain text.
- **`.claude-plugin` marketplace/plugin manifests re-synced to 3.16.0** — they
  were left at 3.15.1 by the v3.16.0 release (PyPI package was correct).

## v3.16.0 — 2026-06-29

### Added
- **Relay account balance in no-quota mode (`show_balance`, default on, auto).**
  When you're on a third-party relay / API key (no official 5h/7d quota), the bar
  can now show `bal $X.XX` — your remaining relay balance. A detached helper
  probes the relay's OpenAI-compatible billing endpoint
  (`/dashboard/billing/subscription` + `/usage`, the new-api / one-api de-facto
  standard) with your key, computes `hard_limit − used/100`, and caches it 5 min
  (a relay that 404s is remembered as unsupported for 1 h, so we don't re-probe
  every render). Fully automatic: **shown only if the relay actually answers,
  silently hidden otherwise** — subscribers and unsupported relays see nothing,
  zero config. The probe always runs in a separate process (like the git
  dirty-state refresh), so it never blocks the bar; the default `Python-urllib`
  User-Agent is replaced because some Cloudflare-fronted gateways 403 it. Turn
  off with `cs config set show_balance false`.

---

## v3.15.1 — 2026-06-29

### Fixed
- **`git status` refresh no longer strands `.git/index.lock`.** The background
  dirty-state poll now runs with `--no-optional-locks`, so a slow repo hitting
  the 2 s timeout (and getting killed) can't leave a stale lock that blocks your
  own next `git add` / `commit` / `rebase`.
- **`cs config set warning_threshold` / `critical_threshold` now actually
  affect the bar.** The render path hardcoded 30/70 and never read the saved
  config; severity thresholds now resolve **CLI flag → env → config → default**.
- **Context-window colour is consistent across modes.** The model name's
  context-fill colour now uses the 70/85 context band (not the 30/70 comfort
  band), so ~35% context reads calm green instead of a false yellow in quota
  mode — matching the no-quota `ctx[…]` bar. Applied to all three styles.
- **Per-session no-quota detection under the shared daemon.** Relay /
  `CLAUDE_CODE_USE_BEDROCK` / `CLAUDE_CODE_USE_VERTEX` env signals are now read
  per session (stamped by the thin client into the payload) instead of the
  daemon's frozen start-time `os.environ`, fixing mis-detection when sessions
  with different backends share one daemon.
- Concurrent `git status` cache writes use a unique temp file (no more
  cross-write corruption / 30 s freeze); the reset-time exception fallback
  returns `--` instead of a wrong "next 2 PM (local)" estimate.

### Changed
- Removed the orphaned claude-monitor cache subsystem (`try_original_analysis`,
  `direct_data_analysis`, `cache_refresh.py`, and the `cache.py`
  `read_cache`/`write_cache`/`refresh_cache_background` trio) — all dead code.
  The displayed `$` figure comes from Claude Code's own `session_cost_usd`, so
  no local token pricing is needed. Net −430 lines, no behaviour change.

---

## v3.15.0 — 2026-06-22

### Added
- **No-quota mode for third-party relays / Bedrock / Vertex.** When Claude Code
  points at a relay (`ANTHROPIC_BASE_URL` ≠ `api.anthropic.com`) or a cloud
  backend (`CLAUDE_CODE_USE_BEDROCK` / `CLAUDE_CODE_USE_VERTEX`), Anthropic's
  official 5h/7d quota doesn't exist — so the bar now drops the two quota
  battery bars and **promotes the context window to its own `ctx[…]` battery
  bar** (green→yellow→red on 70/85% used), keeping the model name, prompt-cache
  countdown, and live-activity tail. Previously the bar showed empty quota bars
  or, worse, back-filled a previous official session's cached quota as fake
  current numbers. Implemented for all three styles (classic / capsule /
  hairline); inspired by [claude-hud](https://github.com/jarrodwatts/claude-hud).
- Detection is automatic (`api_mode = auto`, the default), with a transcript
  heuristic (gated on a Claude Code version that emits rate_limits, so old-client
  official users aren't misread) as a fallback when the env var doesn't reach the
  statusLine subprocess. Force with `cs config set api_mode on` or `CS_API_MODE=on`;
  disable with `api_mode off`. Works under both the inline and daemon render paths.

---

## v3.14.1 — 2026-06-16

### Changed
- **Projection coloring red line lowered to 85% (yellow now 70–84%, green
  below 70%).** A 7d window projecting `→99%` was showing yellow because red
  only started at the cap (100%) — but the `→NN%` chip is clamped to 100 and
  the slow 7d window can sit at 99% for a long time, so "basically going to run
  out" was reading as merely warm. Red now starts at 85%, where a projection is
  effectively a sure exhaustion. The `→NN%` chip itself now uses the same
  red/yellow lines as the bar so they never disagree.

---

## v3.14.0 — 2026-06-16

### Changed
- **Rate-limit windows (5h/7d) now color by where usage is HEADED, not where it
  is right now.** Once a `→NN%` end-of-window projection exists, the window's
  bar fill, label, and ⏰ clock take a severity from the *projected* value
  against the cap: green below 80%, yellow 80–99%, red at 100%. The bar's fill
  LENGTH and printed % still track current usage — only the color is projected.
  So a 7d window sitting at 24% but on track for →96% now reads yellow instead
  of a falsely-healthy green. Applies to all three styles (classic bar, capsule
  `●` dot, hairline mini-bar). Before a projection exists, the window falls back
  to current-usage coloring on the configured thresholds (unchanged).

### Fixed
- **The `→NN%` projection no longer reads far too low for the first ~15 minutes
  after a window resets.** The smoother was seeded from the `used=0` first
  post-reset tick (where the raw projection collapses to the bucket prior ~2%),
  then crawled up with an 8-minute time-constant — so a 5h window 6 minutes in
  at 1% used showed `→14%` when the pace already implied ~50%+. The projection
  now holds the `→--` placeholder until `MIN_ELAPSED` (5h=10m, 7d=1h) — the same
  floor the ⚡ETA chip already uses — and then seeds from the first trustworthy
  reading (no lag). During the hold the window colors by current usage, an
  honest "not enough signal yet" instead of a fake-precise low number.

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
