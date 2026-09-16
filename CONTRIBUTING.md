# Contributing to claude-statusbar

Thanks for considering a contribution. This project is small, opinionated, and
optimized for the realities of running ~60 renders/minute inside Claude Code's
`statusLine` hook — keep that constraint in mind when adding features.

## Quick start

```bash
git clone https://github.com/leeguooooo/claude-code-usage-bar
cd claude-code-usage-bar
uv sync --group dev
uv run pytest tests/             # 320+ tests, ~1.5s
```

For an editable install that also wires up your local `cs` binary:

```bash
uv tool install --reinstall -e .
```

## Running tests

```bash
PYTHONPATH=src uv run pytest tests/        # full suite
PYTHONPATH=src uv run pytest tests/test_progress.py -v   # one file
PYTHONPATH=src uv run pytest -k color_overrides           # by keyword
```

The `PYTHONPATH=src` workaround is needed when an older site-package shim
shadows the editable install. CI runs without it.

### Performance tests

`tests/test_import_perf.py` pins which modules **must not** be imported on
the render fast-path (`render_thin.py`). The render path runs 60×/min — every
import gets multiplied by that. If you add a new dependency, run this test
specifically and add an entry to the banned list if appropriate.

## Architecture in 60 seconds

- `cli.py` — argv dispatch. Routes to `core.main()` for the inline path.
- `render_thin.py` — daemon fast-path. Reads stdin, writes per-session bucket,
  prints daemon-rendered ANSI. Must stay leaf-import; tests enforce this.
- `core.py` — orchestrates stdin parsing, payload computation, render dispatch.
- `progress.py` — pure rendering for the classic style.
- `styles.py` — `render_classic / render_capsule / render_hairline`. Every
  style takes a `Theme`, severity colors come from `theme.s_*`.
- `themes.py` — `Theme` dataclass + 9 built-in palettes + `parse_hex_color` /
  `apply_color_overrides` helpers.
- `config.py` — read/write `~/.claude/claude-statusbar.json`. Validation
  happens here.
- `daemon.py` / `service.py` — long-lived daemon for fast mode (`cs --setup --fast`).
- `commands/`, `skills/` — bundled Claude Code slash commands and the
  consolidated `claude-statusbar` skill, copied into `~/.claude/{commands,skills}/`
  by `cs install-commands` / `cs install-skill`.

The two memory files at
`~/.claude/projects/-Users-leo-github-com-claude-statusbar-monitor/memory/architecture.md`
go deeper if you have access.

## Coding conventions

- **TDD when it pays.** Bug fixes get a regression test first. New features
  get tests that pin invariants, not implementation. Threshold/severity logic
  always gets a test.
- **No raw 8-color ANSI.** Severity colors come from `theme.s_*`. Mute /
  edge / ink come from `theme.mute / edge / ink`. The legacy `\033[32m`
  constants were removed in v3.4 — do not reintroduce them.
- **Visual identity is sacred.** Battery bar, `[ ]` brackets, `🕐` / `⏰`
  clock emojis, ` | ` separators, `(used/size)` parens — these are the
  product's identity. Refinements happen *inside* this language (color,
  spacing, hierarchy), not by replacing it.
- **YAGNI ruthlessly.** A bug fix doesn't need surrounding cleanup; a
  one-shot operation doesn't need a helper. Three similar lines is better
  than a premature abstraction.
- **No comments unless the WHY is non-obvious.** Don't narrate WHAT the
  code does; well-named identifiers do that.

## Pull request flow

1. Open an issue first for non-trivial changes — saves a round-trip if the
   approach needs adjusting.
2. Branch from `main`. Branch name shouldn't include `claude` or `gpt` (just
   describe the change: `feat/cost-pill-recolor`, `fix/falsy-zero-ctx`, etc.).
3. Run `PYTHONPATH=src uv run pytest tests/` — must be green.
4. Commit messages follow [Conventional Commits](https://conventionalcommits.org/):
   `feat(scope): ...`, `fix(scope): ...`, `refactor(scope): ...`, `docs: ...`,
   `release: vX.Y.Z — ...`. Bodies should focus on *why*.
5. Push, open a PR. The PR description should include:
   - One-paragraph summary
   - Test plan (commands you ran)
   - Any visual diff (before/after `cs preview` if colors/layout changed)

## Releasing (maintainers)

**The version bump is the release.** Land a commit on `main` that changes
`version` in `pyproject.toml` and `.github/workflows/release.yml` does the
rest: cuts the tag, publishes the GitHub Release with this version's CHANGELOG
section as its notes, builds and attaches the platform binaries, and uploads
the wheel to PyPI.

So a release is an ordinary PR:

```bash
# 1. bump the version in pyproject.toml, .claude-plugin/plugin.json and
#    .claude-plugin/marketplace.json (all three must agree — the workflow
#    refuses to release on drift)
# 2. add the vX.Y.Z section to CHANGELOG.md — it becomes the release notes,
#    and its bold one-liner becomes the release title
# 3. open a PR as usual, merge it
python scripts/release_meta.py check   # same gate the workflow runs
```

Re-running is safe: once the tag exists the workflow skips everything, so a
re-push of `main` cannot cut a second release. To release without a new bump
(a re-run after a failed upload, say), use **Actions → Release → Run workflow**
and give it the version.

Still manual: syncing the marketplace entry in `leeguooooo/plugins`.
`./publish.sh` remains for a hand-rolled PyPI upload, but the workflow is the
normal path.

## Reporting bugs

Run `cs doctor` first — it self-checks settings, daemon state, and cache
health. Paste its output in the issue.

A useful bug report includes:
- `cs --version`
- `cs doctor` output
- Your terminal emulator + version
- A reproducible stdin payload if you can capture it (e.g.
  `cat ~/.cache/claude-statusbar/last_stdin.json`)

## License

Contributions are accepted under the project's [MIT license](LICENSE).
