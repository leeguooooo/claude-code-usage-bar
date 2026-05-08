# HN prepared answers

Copy-paste templates for the most likely Show HN comments. Tone: technical, factual, concede when the criticism is fair, link to code instead of arguing. Don't argue with bad-faith comments — let other commenters do that.

**Speed matters more than depth.** Reply within 2-3 minutes of a comment landing on a top-tier thread. Long delay = HN algorithm assumes the post is dead.

---

## 1. "How is this different from ccusage / Claude-Code-Usage-Monitor?"

> Different form factor, not different features. ccusage and Claude-Code-Usage-Monitor are excellent **standalone TUIs** — you open them in a separate terminal and look at the dashboard when you want to. They have things I don't (cost analytics, burn-rate prediction).
>
> This is the **statusLine** version. Claude Code added a hook that runs a command on every prompt and renders the output at the bottom of the chat. So this is one line, always visible while you're typing, no Cmd+Tab. Trade-off: less data per glance, zero context-switch cost.
>
> I run both. ccusage in a tmux pane for analysis, this in Claude Code for peripheral awareness. They don't compete.

---

## 2. "Why Python? Why not Rust / Go?"

> Honest answer: Python imports are the bottleneck (~13ms cold start), and v3.6.0 makes daemon mode the default — a long-lived daemon pre-renders into a file, the statusLine command (`cs render`) is a thin reader that just `cat`s the file. Each tick is 3-5ms, total CPU under 1% continuously.
>
> Rust would shave maybe 10ms off the cold path which doesn't matter once the daemon is running. The whole project is ~3K lines of Python which is easy for contributors to fork. The friction-to-contribution math beats the cold-start math here.

---

## 3. "Doesn't the daemon increase complexity / risk?"

> Fair concern. Two design choices to keep it boring:
>
> 1. The daemon **isn't required**. If it dies or freezes, the thin client (`cs render`) detects `rendered.meta.json` is older than 5s and falls back to inline render — and lazily re-spawns the daemon in the background. You never see a frozen status line.
> 2. The daemon doesn't talk to the network. It reads stdin from Claude Code, writes a pre-rendered ANSI string to `~/.cache/claude-statusbar/sessions/<session-id>/rendered.ansi`. That's it.
>
> Optional launchd / systemd integration is opt-in (`cs daemon install`). Default install just spawns the daemon as your user process. If you want it gone, `cs daemon stop` or `cs --setup --inline`.

---

## 4. "What does it actually send / phone home?"

> Nothing. Zero network egress except the once-per-day PyPI version check (`updater.py`), which you can disable with `--no-auto-update` or `CLAUDE_STATUSBAR_NO_UPDATE=1`. All rate-limit data comes from Claude Code's stdin payload — Anthropic's API headers, surfaced by Claude Code itself. We just parse and render it.
>
> Source: https://github.com/leeguooooo/claude-code-usage-bar/blob/main/src/claude_statusbar/updater.py

---

## 5. "Windows support?"

> macOS and Linux work. Windows isn't tested — the daemon path uses Unix sockets and the launchd / systemd integrations are POSIX-only. Inline mode (`cs --setup --inline`) might work on Windows but I haven't verified. PRs welcome from someone with a Windows + Claude Code setup.

---

## 6. "Is this from Anthropic?"

> No, third-party. Built on Claude Code's public `statusLine` hook
> (https://docs.claude.com/en/docs/claude-code/statusline). MIT licensed,
> not affiliated with Anthropic.

---

## 7. "How does this avoid stale data between prompts?"

> The data path:
> 1. Claude Code runs the statusLine command on every prompt and on its `refreshInterval` (we default to 1s).
> 2. When the user submits a request, Anthropic's response includes rate-limit headers; Claude Code passes those into the statusLine command's stdin.
> 3. We parse and render. We also cache the latest stdin so between requests (when stdin has no rate_limits) we can keep showing the last-known values with rolled-forward window math.
>
> Caveat: the 5h/7d percentages can only refresh when you actually make a request, since that's when Anthropic returns fresh headers. Between requests we extrapolate the countdown but the % stays static. ccusage hits the same limitation — it's an Anthropic-API thing, not a tool thing.

---

## 8. "Can I customize colors / make my own theme?"

> Yes. v3.4 added per-segment severity colors (each metric colors itself by its own severity threshold). Override the OK/warn/hot colors with:
>
> ```
> cs config set color_ok '#4ec85b'
> cs config set color_warn '#e6be5a'
> cs config set color_hot '#e85050'
> ```
>
> Adding a whole new theme is ~20 lines in `src/claude_statusbar/themes.py` — open an issue with the colors you want and I'll add it, or send a PR. Theme PRs are the easiest contribution path.

---

## 9. "Why does it need `refreshInterval: 1`? That's wasteful."

> v3.6.0 ships daemon mode by default specifically because of this concern. Inline + 1Hz is ~3% CPU continuously (Python startup × 60/min). Daemon mode brings it to <1% — the daemon ticks once per second, the statusLine command reads a pre-rendered file. That's the whole reason daemon mode exists.
>
> If you want even quieter, `cs --setup` preserves any explicit `refreshInterval` you've set in `~/.claude/settings.json`. Set it to `30` or `60` and the cache-age countdown gets choppier but CPU drops further.

---

## 10. "Show me the code path for X" / hostile review

> Best response: link to the specific file/line. Don't defend, just point.
>
> ```
> Setup logic: src/claude_statusbar/setup.py
> Render path: src/claude_statusbar/core.py
> Thin client: src/claude_statusbar/render_thin.py
> Daemon: src/claude_statusbar/daemon.py
> ```
>
> If they're right about a bug, say so and open an issue. HN respects "yeah you're right, filed it: <link>".

---

## Triage rules during the launch window

**Reply order**:
1. Top of thread (visibility)
2. Anything questioning correctness or security (let those simmer = death)
3. Easy wins (theme requests, "this is great")
4. Long technical critiques last (need real thought, but if you nail one of these you get HN street cred)

**Don't reply to**:
- Bare "+1" / "looks cool" — engages your karma but burns time
- Off-topic threads (Claude vs ChatGPT, AI doomer stuff)
- Bait ("Anthropic is going to kill you / make this themselves" — true and irrelevant)

**Have on hand for fast paste**:
- Repo: https://github.com/leeguooooo/claude-code-usage-bar
- PyPI: https://pypi.org/project/claude-statusbar/
- Code of Conduct exists, CI green, MIT
- Comparison table (in README): https://github.com/leeguooooo/claude-code-usage-bar#comparison-with-alternatives
