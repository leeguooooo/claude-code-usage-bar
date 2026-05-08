# Security Policy

## Supported versions

`claude-statusbar` ships from `main`. Only the latest minor release receives
security fixes. Older versions auto-update from PyPI on a daily check, so
"latest" is also typically what users are running.

| Version | Supported |
|---|---|
| 3.5.x | ✅ |
| 3.4.x | ✅ (auto-updates to 3.5) |
| < 3.4 | ❌ |

## What counts as a security issue

`cs` runs as part of Claude Code's `statusLine` hook — it reads stdin
(JSON from Claude Code), reads/writes a small set of files under
`~/.claude/` and `~/.cache/claude-statusbar/`, and may spawn a long-lived
daemon. Security-relevant cases include:

- **Arbitrary command execution** via crafted stdin payload, malformed
  config, or a crafted theme/style name.
- **Path traversal** that lets `cs` read or write outside its expected
  directories (`~/.claude/`, `~/.cache/claude-statusbar/`,
  `~/.local/share/uv/tools/`).
- **PID confusion** — `cs daemon stop` signaling a process the user
  doesn't own. (We already check `cmdline` / `ps -o command=` before
  signaling; report any way around that check.)
- **JSON / config-file corruption** that breaks Claude Code itself.

Performance regressions, theme bugs, broken render output, and
"the bar shows wrong numbers" are **not** security issues — file those
as regular GitHub issues.

## Reporting

Email **leeguooooo@gmail.com** with the subject line
`[SECURITY] claude-statusbar`. Include:

- A clear description of the issue and impact.
- Steps to reproduce, ideally a minimal stdin payload or config snippet.
- Affected version(s) — include `cs --version` output.

I'll acknowledge within 7 days and aim to ship a fix within 30 days for
confirmed issues. Critical issues (RCE, write-outside-of-expected-dirs,
PID hijack) get prioritized over feature work.

Please **do not** open a public GitHub issue for unpatched security bugs.
You can also use [GitHub's private vulnerability reporting](https://github.com/leeguooooo/claude-code-usage-bar/security/advisories/new)
if you prefer not to email.

## Disclosure

Once a fix is shipped to PyPI, a CVE entry (when applicable) and a
disclosure note in `CHANGELOG.md` will land. Reporters are credited unless
they request otherwise.
