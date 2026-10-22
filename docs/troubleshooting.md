# Troubleshooting, diagnostics & upgrading

## `cs doctor` — self-diagnostic

If the status bar isn't behaving the way you expect, run:

```bash
cs doctor
```

It prints (with red ✗ for anything off):

- Which `cs` binary the OS will resolve, plus its version + Python interpreter
- Whether a newer release is available (from the updater's cache, no network call) and whether auto-upgrade is on, off, or blocked
- Whether `~/.claude/settings.json` has *our* statusLine entry (vs missing / vs another tool's)
- How fresh `~/.cache/claude-statusbar/last_stdin.json` is (so you can tell if Claude Code is actually pushing data)
- If the daemon is running (fast mode) — its pid and how stale `rendered.ansi` is
- Terminal size and `TERM`
- Current resolved `style` / `theme` / all `show_*` toggles
- Slash commands installed under `~/.claude/commands/`

Paste the output verbatim in any bug report — it's almost always enough to diagnose remotely.

## Common problems

**Status line doesn't appear after install** — Restart Claude Code (settings.json is read at session start). If still missing, run `cs doctor` and check the `statusLine entry` row.

**`cs doctor` says "missing"** — A Claude Code upgrade can wipe `statusLine` from `~/.claude/settings.json`. Run `cs --setup` (or `cs --setup --fast` if you want daemon mode) to restore it. The package also self-heals once per day automatically.

**Quota is unknown after an account switch** — The bar waits for that account's rate-limit data. It does not reuse another account's cached quota. Once Claude Code sends a response with quota, all windows for that account share the new reading.

**Balance shows `⟳`** — The relay usage query failed. The amount is the last valid reading, not a newly confirmed balance; the client retries in the background.

**Numbers stuck / not updating** — Two possibilities:
1. `refreshInterval` not set — Claude Code only re-renders on activity. Add `"refreshInterval": 30` (or `1` for live cache-age).
2. Daemon mode running stale data — `cs daemon stop && cs daemon start`. Or just `cs doctor` and check `daemon` row freshness.

**Cache-age segment shows `cache 0s` and never moves** — `refreshInterval` is unset; Claude Code only re-invokes the statusLine on each user/assistant turn. Set `"refreshInterval": 1` in settings.json. For 1Hz refresh you'll also want `cs --setup --fast` so the per-second invocation stays cheap.

**`cs --setup --fast` then daemon shows wrong rate-limits** — Fixed in v3.2.1. Upgrade with `cs upgrade`.

### Stuck on an old version

Auto-upgrade checks every 6 hours while Claude Code is running. These releases
shipped an updater that cannot upgrade itself; run `cs upgrade` once (or re-run
the install one-liner) and auto-upgrade works from then on:

| You are on | Why it never upgrades | Fix once |
|---|---|---|
| uv install ≤ 3.29.3 whose daemon runs as a launchd/systemd service | the service couldn't find uv and fell back to pip, which a uv env lacks | `cs upgrade` |
| standalone binary ≤ 3.33.0 | no CA certificates bundled, every HTTPS check failed | re-run `install.sh` |
| standalone binary < 3.36.0 | binaries had no auto-upgrade yet | `cs upgrade` or `install.sh` |
| uv install 3.35.2–3.42.x | misread as a duplicate install (#71) | see below |
| Windows < 3.43.6 | auto-upgrade never ran on Windows | close Claude Code, `cs daemon stop`, `uv tool upgrade claude-statusbar` |
| Windows pip / pipx (any) | can't replace files in use | close Claude Code, then `pip install -U claude-statusbar` |
| two installs of `cs` | the copy that doesn't own `cs` won't upgrade itself | `cs doctor` names both; remove one |

**Stuck on an old version (uv installs on 3.35.2–3.42.x)** — Those versions misread a `uv tool install` as a duplicate install and skip every auto-upgrade, so they can't fix themselves ([#71](https://github.com/leeguooooo/claude-code-usage-bar/issues/71)). On macOS/Linux run `cs upgrade` once; auto-upgrade works normally afterwards. On Windows with uv below 3.43.7, don't use `cs upgrade` (it can leave `cs` broken, #66): close Claude Code, run `cs daemon stop`, then `uv tool upgrade claude-statusbar`. From 3.46.1, `cs doctor` flags a blocked auto-upgrade and an available update.

**Auto-update is annoying / blocked** — `export CLAUDE_STATUSBAR_NO_UPDATE=1` in your shell rc.

For anything else: open a [GitHub issue](https://github.com/leeguooooo/claude-code-usage-bar/issues) with the output of `cs doctor` attached — it captures version, paths, settings.json state, daemon state, and recent cache freshness in one paste.

## Upgrading

Auto-updates in the background (checked every 6 hours; the standalone binary from
GitHub Releases, pip/pipx/uv installs from PyPI). To upgrade manually, one command works for
every install (pip, pipx, or uv — it detects which one is actually running `cs`
and uses that, so you never need to know or guess):

```bash
cs upgrade
```

Don't reach for `uv tool install`/`pipx upgrade` by hand — if you installed via
`pip`, you may not even have those tools, and running the wrong one can leave
you with two parallel installs. `cs upgrade` picks the right channel for you.

To disable auto-updates: `export CLAUDE_STATUSBAR_NO_UPDATE=1`


## Network and custom-endpoint notices

`show_ip_risk` stays opt-in. A fresh low-risk result is silent; unavailable,
failed or stale observations display **unknown**, with an explicit last-known
label when retaining an old warning. A difference between IPv4/IPv6 exit
countries does not establish a leak or Claude's actual route. Scores and local
configuration do not predict account suspension. Custom-endpoint notices do
not inspect request metadata or infer a watermark from your timezone.

Run `cs doctor` for cached coverage and these detailed checks:

- [IP Check](https://ip-check.leeguoo.com/#local-diagnostics): network and browser-visible observations.
- [Thermo for macOS](https://app.leeguoo.com/thermo): local checks; verify whether your installed version includes Claude diagnostics.

The status line does not invoke Thermo, install it, or scan installation IDs and
Sentry files on each render. The new `cs doctor` risk summary reads existing
cache only and omits raw endpoint URLs. Doctor's existing render/shell smoke
tests still act like normal status-line invocations and may refresh enabled
background collectors; they do not launch Thermo.
