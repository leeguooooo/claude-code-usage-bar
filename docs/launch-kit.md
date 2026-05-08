# Launch kit

Copy-paste materials for promoting `claude-statusbar`. Strategy: don't compete head-on with ccusage / Claude-Code-Usage-Monitor — they own the **dashboard** niche. We own the **statusLine** niche. Pitch from that angle every time.

---

## 1. X / Twitter thread (English)

**Tweet 1 (the hook + hero asset)**
> Your Claude Code rate limits, in one line — at the bottom of every prompt.
>
> 5h / 7d window usage. Reset countdowns. Current model + context window. Prompt-cache freshness. No second terminal, no context switch.
>
> `pip install claude-statusbar && cs --setup`
>
> [attach: docs/images/hero.svg or recorded GIF]

**Tweet 2**
> Why a statusLine instead of a TUI dashboard?
>
> Because you don't *want* to look. You want to glance. The information is there in your peripheral vision while you're typing — no Cmd+Tab, no second window stealing focus.

**Tweet 3**
> 3 styles × 9 themes. Per-segment severity colors (green / yellow / red by metric). Catppuccin, Dracula, Nord, Tokyo Night, Sakura, Mono — pick what doesn't fight your terminal theme.
>
> [attach: 2-3 theme screenshots from docs/images/]

**Tweet 4**
> Daemon "fast mode" for `refreshInterval=1` — ~5× lower CPU than re-running Python on every tick.
>
> Auto-updates from PyPI. Self-diagnostic with `cs doctor`. Natural-language config via the bundled Claude Code skill: *"switch theme to nord"* → done.

**Tweet 5 (call to action)**
> Free, MIT, Python ≥ 3.9. PyPI: https://pypi.org/project/claude-statusbar/
> GitHub: https://github.com/leeguooooo/claude-code-usage-bar
>
> If you've ever thought "I wish I knew how close I was to the 5h reset without leaving my editor" — this is that.

---

## 2. X / Twitter thread (中文版)

**1**
> Claude Code 5h / 7d 用量、重置倒计时、当前模型 + 上下文窗口、prompt-cache 新鲜度——全部塞进 Claude Code 底部那一行 statusLine 里。
>
> 不开第二个终端，不切窗口。
>
> `pip install claude-statusbar && cs --setup`
>
> [附 hero.svg]

**2**
> 为什么不做 TUI dashboard？
>
> 因为你不想"看"——你想"瞥"。状态栏永远在你余光里，dashboard 要 Cmd+Tab。这是两种心智，不是产品差距。

**3**
> 3 种 style × 9 套主题。每个字段独立按严重度上色（绿 / 黄 / 红）。Catppuccin、Dracula、Nord、Tokyo Night、Sakura、Mono——挑一个不打架你终端配色的。

**4**
> daemon fast-mode：`refreshInterval=1` 时 CPU 比纯 Python 重新跑低约 5 倍。自动从 PyPI 更新。`cs doctor` 自检。自带 Claude Code skill 支持自然语言改配置——*"主题换 nord"* → 自动调对的命令。

**5**
> 免费、MIT、Python ≥ 3.9。
> PyPI: https://pypi.org/project/claude-statusbar/
> GitHub: https://github.com/leeguooooo/claude-code-usage-bar

---

## 3. Reddit r/ClaudeAI post

**Title**
> I built a one-line statusLine for Claude Code that shows your 5h / 7d rate-limit usage in real time

**Body**
> Hey — I've been using Claude Code heavily and kept Cmd+Tab'ing to a separate terminal running ccusage / Claude-Code-Usage-Monitor to check how close I was to the 5h reset. Got tired of it and built a `statusLine` integration instead.
>
> It's one line at the bottom of Claude Code itself:
>
> `5h[████░░░░░░]⏰1h28m | 7d[███████░░░]⏰11h28m | Opus 4.7(350.0k/1.0M) | cache 4m23s`
>
> [hero asset]
>
> **What it shows**
> - 5h and 7d rate-limit usage with reset countdowns (from Anthropic's API headers)
> - Current model + context window usage
> - Prompt-cache age (so you know when your cache is about to expire)
> - Optional: session cost
>
> **What it isn't**
> - Not a replacement for ccusage / Claude-Code-Usage-Monitor — those are great dashboards. This is the *peripheral vision* version. I run both.
>
> **Setup**
> ```
> pip install claude-statusbar && cs --setup
> ```
> Restart Claude Code. Done.
>
> 3 styles × 9 themes (Catppuccin, Dracula, Nord, Tokyo Night, etc.). Daemon fast-mode for low CPU at high refresh rates. Open source, MIT.
>
> Repo: https://github.com/leeguooooo/claude-code-usage-bar
>
> Happy to take feature requests / theme suggestions.

---

## 4. Hacker News post (Show HN)

**Title**
> Show HN: Claude-statusbar – one-line rate-limit display inside Claude Code

**First comment (post immediately after submitting)**
> Author here. Quick context on why this exists vs. ccusage / Claude-Code-Usage-Monitor:
>
> Both of those are excellent standalone TUIs — you open them in a separate terminal and look at the dashboard when you want to know your status. They have features I don't (cost analytics, burn-rate prediction).
>
> What I wanted was the opposite: information that's *always* visible without me having to ask. Claude Code added a `statusLine` hook that runs a command on every prompt and renders the output at the bottom of the chat. This package is a fast (~13 ms cold, ~3 ms via daemon) renderer for that hook.
>
> The trade-off: less data per glance, but zero context-switch cost. I've found that "always visible peripheral information" changes how I pace work near a rate limit — I throttle myself naturally instead of finding out I'm at 95% by surprise.
>
> Open to questions / feedback.

---

## 5. ProductHunt launch copy

**Tagline (60 chars)**
> One-line Claude Code statusLine for 5h/7d rate limits

**Description (260 chars)**
> Real-time Claude Code rate-limit display in the chat itself — not another window. Shows 5h/7d usage, reset countdowns, model, context window, prompt-cache age. 3 styles × 9 themes. Daemon fast-mode. MIT. `pip install claude-statusbar`.

**First comment**
> Built this because I was Cmd+Tab'ing to a separate Claude usage TUI 50 times a day. The Claude Code `statusLine` hook lets you render anything you want at the bottom of every prompt — so I made the lightest, fastest renderer I could and packaged it on PyPI.
>
> Not replacing ccusage / Claude-Code-Usage-Monitor (those are dashboards). This is the peripheral-vision version that lives inside Claude Code itself.
>
> First-time PH launcher; happy to answer anything.

**Categories**
- Developer Tools
- Productivity
- Artificial Intelligence

**Topics / hashtags**
`claude` `claude-code` `developer-tools` `productivity` `cli` `python` `terminal`

---

## 6. Blog post draft — "Why a statusLine, not another TUI"

> # Why I built a Claude Code statusLine instead of another usage TUI
>
> There are already two excellent open-source tools for monitoring Claude Code usage: [ccusage](https://github.com/ryoppippi/ccusage) (~14k stars) and [Claude-Code-Usage-Monitor](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor) (~8k stars). Both are TUIs you run in a separate terminal. Both are well-built.
>
> I built a third thing anyway. It's a `statusLine` integration — one line, in the chat itself, no separate window. Here's the reasoning.
>
> ## The TUI dashboard form factor has a hidden cost
>
> A TUI dashboard answers the question *"what's my status?"* really well. The problem is that you have to *ask* — Cmd+Tab to the other terminal, look at the screen, Cmd+Tab back. Each round trip is maybe 2 seconds. Multiply by the number of times you check per day.
>
> But the bigger cost isn't the seconds. It's that you only check when something prompts you to — usually when you've already hit a wall. *"Why did Claude just refuse this prompt?"* Cmd+Tab, *oh, I'm at 98%*.
>
> What I actually wanted was for the answer to be in my peripheral vision *before* the question forms. So I'd pace myself naturally as the bar fills, instead of crashing into the limit.
>
> ## What `statusLine` is
>
> Claude Code [exposes a hook](https://docs.claude.com/en/docs/claude-code/statusline) that runs a command on every prompt and renders the stdout at the bottom of the chat. Anything you put there is *always* visible while you're typing.
>
> So my problem reduced to: write a command that prints my Claude usage, fast enough that running it on every prompt is invisible (~13 ms cold, ~3 ms via daemon). That's `claude-statusbar`.
>
> ## Why not just add `--statusline` to ccusage?
>
> A few reasons it's a different product:
>
> 1. **Render budget is tiny.** A statusLine has maybe 80–120 columns. ccusage's TUI shows tables; that doesn't compress to one line. The information has to be selected and encoded differently — battery bars, severity colors, glyphs (`⏰` for "until reset"). It's a different design problem.
> 2. **Cold-start matters.** A TUI you launch once and let run; a statusLine command runs *every prompt*. Python imports alone are 100+ ms if you're not careful. We use lazy imports, optional daemon mode, and a thin client to keep the floor under 13 ms.
> 3. **No window of its own** means no scrollback, no charts, no history view. You give up everything except the single most recent reading.
>
> ## What you give up
>
> Real things, not handwaving:
>
> - **No cost analytics.** `cs` shows session cost optionally; it doesn't aggregate by day/week. If you want a dashboard with charts, run ccusage in a side pane.
> - **No burn-rate prediction.** Claude-Code-Usage-Monitor will tell you "at this pace you'll run out at 4:32 PM." `cs` shows you the bar; you do the prediction.
> - **No history.** It's stateless by design. The data is in Anthropic's headers; we just render it.
>
> The tools coexist nicely. I have ccusage running in a side tmux pane and `cs` in my Claude Code statusLine. Different jobs.
>
> ## How to try it
>
> ```
> pip install claude-statusbar
> cs --setup
> ```
>
> Restart Claude Code. There's a `cs doctor` if it doesn't show up.
>
> Repo: https://github.com/leeguooooo/claude-code-usage-bar
>
> If you have a theme you'd like, open an issue — adding themes is the simplest contribution path and they're useful to other people.

---

## 7. Recording a real GIF (replaces hero.svg if you want)

The current hero is an animated SVG. For Twitter / Reddit / PH, a real terminal-recorded GIF travels better. Recommended pipeline on macOS:

```
brew install asciinema agg
asciinema rec --idle-time-limit 1 hero.cast
# do a 20-30s session: cs preview, theme switch, normal Claude Code usage
agg --font-size 16 --theme monokai hero.cast hero.gif
```

Aim for **<8 MB** so Twitter inlines it instead of attaching as a file. 30 fps is overkill — 15 fps is fine for terminal output and halves the size.

Drop it into `docs/images/hero.gif`. Don't replace `hero.svg` in the README — the SVG renders inline on GitHub mobile and is 3 KB. The GIF is for off-platform sharing only.

---

## Checklist

- [x] Update GitHub repo description + topics (done in this commit)
- [ ] Record `docs/images/hero.gif` (asciinema + agg, see §7)
- [ ] Post X thread (English first, Chinese version 24h later)
- [ ] Submit Show HN (Tuesday 9 AM PT is the empirically best window)
- [ ] Post r/ClaudeAI
- [ ] Submit ProductHunt (use a Tuesday or Wednesday; avoid Mondays)
- [ ] Publish blog post (cross-post to dev.to and Medium for SEO)
- [ ] Comment on top "how do I monitor Claude usage" Reddit threads with a polite *"if you specifically want it inside Claude Code, [link]"* — do not spam

## Things to watch

- **GitHub stars** — set a 90-day target of 750 (we're at 229, growing ~75/mo organically). A successful X thread + Show HN can pull 200–400 in a weekend.
- **PyPI installs** — `pepy.tech/project/claude-statusbar` is on the README badge. Watch the monthly trend post-launch.
- **Issue volume** — sudden bug-report spike after launch is normal; budget 2–3 days for triage.
