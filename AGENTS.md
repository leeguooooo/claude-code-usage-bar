# Repository Guidelines

## Project Structure & Module Organization
- Core code lives in `src/claude_statusbar`: `core.py` handles usage calculation and model lookup, `cli.py` provides the entrypoint (`claude-statusbar`, `cstatus`, `cs`), and `updater.py` manages self-upgrades.
- Packaging metadata is in `pyproject.toml`; built artifacts land in `dist/` (keep generated wheels/sdists out of commits unless releasing).
- Installer helpers: `install.sh` and `web-install.sh` for one-line setup, `uninstall.sh` for cleanup, and `publish.sh` for PyPI uploads. Demo and promotional assets sit in `demo/`, `img.png`, and `promotion/`.

## Build, Test, and Development Commands
- Install for development (editable): `python -m pip install -e .`
- Run locally: `claude-statusbar` (or `python -m claude_statusbar.cli --version` to verify wiring).
- Build distribution: `python -m build` (requires `build`/`wheel`).
- Publish to PyPI: `./publish.sh` (expects `PYPI_API_TOKEN` or `~/.pypirc`; offers TestPyPI first).
- Install optional dependency for richer data: `python -m claude_statusbar.cli --install-deps` then follow prompts for `claude-monitor`.

## Coding Style & Naming Conventions
- Python 3.9+; follow PEP 8 with 4-space indentation and short, imperative helper names (`get_current_model`, `try_original_analysis`).
- Keep dependencies minimal (stdlib only by default); guard optional imports and subprocess calls.
- Prefer pure functions with clear return types; add `typing` hints where missing and keep logging quiet (current default ERROR).

## Testing Guidelines
- No automated suite exists yet; add targeted `pytest` cases around `core.main`, calculation helpers, and file parsing when you touch logic.
- For manual checks: place sample Claude JSONL data under `~/.claude/projects/`, run `claude-statusbar`, and confirm token/cost figures and reset timer behave as expected across empty/malformed files.
- If introducing flags, verify CLI help stays readable: `python -m claude_statusbar.cli --help`.

## Commit & Pull Request Guidelines
- Match existing history: concise lowercase prefixes (`fix: ...`, `feat: ...`, `chore: ...`) with imperative summaries.
- PRs should describe behavior changes, note data sources used (`claude-monitor` vs direct file scan), and include sample output before/after when altering the status line.
- Keep diffs small and focused; avoid committing generated `dist/` or `build/` outputs unless intentionally releasing.

## Security & Configuration Tips
- The tool reads from user-local Claude data under `~/.claude/`; avoid logging or committing any captured traces.
- Publishing requires secrets (`PYPI_API_TOKEN`); export them locally and never bake into scripts. Use TestPyPI when unsure about release artifacts.
