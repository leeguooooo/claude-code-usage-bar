## Summary

<!-- One paragraph: what changes, why. Focus on the "why". -->

## Test plan

- [ ] `PYTHONPATH=src uv run pytest tests/` passes locally
- [ ] If touching the render path: `PYTHONPATH=src uv run pytest tests/test_import_perf.py` passes
- [ ] If touching colors / layout: `cs preview` looks right under at least 2 themes (paste before/after below)
- [ ] If touching config: docs in README + CHANGELOG updated

## Visual diff

<!-- For UI changes, paste a before/after of `cs preview` or describe the visible change. Skip if not applicable. -->

## Checklist

- [ ] Branch name describes the change (`feat/...`, `fix/...`, `refactor/...`)
- [ ] Commit messages follow Conventional Commits
- [ ] CHANGELOG.md updated for user-visible changes
- [ ] No raw 8-color ANSI codes introduced (use `theme.s_*` / `theme.mute` / `theme.ink`)

See [CONTRIBUTING.md](../CONTRIBUTING.md) for the full guide.
