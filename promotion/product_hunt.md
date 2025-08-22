# Product Hunt Launch Template

## 📦 Product Information

**Name:** Claude Status Bar

**Tagline:** Never run out of AI tokens unexpectedly again

**Description (240 chars max):**
Track Claude AI token usage in real-time. One-line installation adds a status bar showing tokens, cost, and time remaining. Color-coded warnings keep you informed. Open source & lightweight.

**Full Description:**
Claude Status Bar is a lightweight monitoring tool that solves a common problem for Claude AI users: not knowing how many tokens you've used until it's too late.

**The Problem:**
Claude's web interface doesn't show real-time usage, leaving developers in the dark about their token consumption until they hit the rate limit.

**The Solution:**
A simple status bar that displays:
- 🔋 Real-time token usage (current/limit)
- 💰 Cost tracking in USD
- ⏱️ Time until session reset
- 📊 Color-coded usage indicators

**Key Features:**
✅ One-line installation that auto-configures everything
✅ Works in Claude Code, terminal, tmux, and shell prompts
✅ Lightweight with minimal dependencies
✅ Open source (MIT license)
✅ Available on PyPI

**Installation is dead simple:**
```bash
curl -fsSL https://raw.githubusercontent.com/leeguooooo/claude-code-usage-bar/main/web-install.sh | bash
```

No manual configuration needed. It just works.

Perfect for developers, data scientists, and anyone using Claude AI for coding.

## 🏷️ Topics/Categories

**Primary Category:** Developer Tools
**Secondary Category:** Productivity

**Topics to add:**
- AI
- Monitoring
- Terminal
- CLI
- Open Source
- Python
- Developer Tools
- Productivity Tools

## 🖼️ Media Assets

### Gallery Images (Required: 1400x788px)

1. **Hero Image:** Screenshot of Claude Code with status bar
2. **Installation:** Terminal showing one-line install
3. **Features:** Diagram showing all features
4. **Integration:** tmux/terminal examples

### Thumbnail (Required: 240x240px)
Logo or icon with "CS" or status bar visualization

## 👥 Makers

**Your Name:** @leeguooooo
**Role:** Maker
**Twitter/X:** [Your handle]

## 🎯 Launch Strategy

### Pre-Launch (Day Before)

1. **Prepare hunters:** Ask 5-10 friends to hunt when live
2. **Schedule launch:** 12:01 AM PST (best time)
3. **Prepare responses:** For common questions
4. **Test everything:** Make sure installer works

### Launch Day

**12:01 AM PST:** Product goes live
**12:05 AM:** Share with your network
**12:30 AM:** Post in relevant Slack/Discord
**6:00 AM:** Share on Twitter/LinkedIn
**9:00 AM:** Post on Reddit
**All day:** Respond to every comment

### Launch Day Checklist

- [ ] Product live at 12:01 AM PST
- [ ] Shared with hunters list
- [ ] Posted on Twitter
- [ ] Shared in communities
- [ ] Responding to comments
- [ ] Thanking hunters
- [ ] Monitoring GitHub for issues

## 💬 Common Questions & Answers

**Q: Does it work with Claude.ai web?**
A: It's designed for Claude Code (desktop app), but the terminal command works anywhere.

**Q: Is it secure?**
A: Yes! It only reads local usage data, no external connections except to PyPI for installation.

**Q: Does it slow down Claude?**
A: No, it's extremely lightweight and runs independently.

**Q: Can I customize the format?**
A: Currently it has a standard format, but PRs are welcome for customization options!

## 📝 Launch Tweet

```
🚀 We're live on @ProductHunt!

Claude Status Bar - Never run out of AI tokens unexpectedly again.

One-line install, real-time monitoring, open source.

Would love your support! 🙏

[Product Hunt Link]

#BuildInPublic #AI #OpenSource
```

## 🎁 Hunter Outreach Template

```
Hey [Name]!

I just launched Claude Status Bar on Product Hunt - it's a tool that shows real-time AI token usage in your terminal.

Would really appreciate your support if you find it useful!

[Product Hunt Link]

It's open source and installs with one command:
curl -fsSL https://raw.githubusercontent.com/leeguooooo/claude-code-usage-bar/main/web-install.sh | bash

Thanks!
```

## 📊 Success Metrics

- **Good:** 100+ upvotes
- **Great:** 200+ upvotes  
- **Amazing:** Top 5 of the day
- **Incredible:** Product of the Day

## 🔗 Important Links

- GitHub: https://github.com/leeguooooo/claude-code-usage-bar
- PyPI: https://pypi.org/project/claude-statusbar/
- Website: GitHub repo (for now)

## 🚨 Crisis Management

If something breaks on launch day:

1. **Acknowledge quickly:** "Thanks for reporting! Looking into it."
2. **Fix ASAP:** Push fixes immediately
3. **Update users:** "Fixed! Please try again."
4. **Thank reporters:** Credit them in fix commits