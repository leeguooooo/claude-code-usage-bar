# Project + branch identity segment — design

## Problem

The status bar today shows usage/quota/cost but no **identity**: which
project, which branch, whether there are unsaved changes. Users with
multiple Claude Code windows on different repos can't tell at a glance
which window is on which project. The bar's existing horizontal real
estate is already dense (battery bar, msgs, weekly, model, ctx, two
reset timers, cache, cost), so cramming identity onto the same line
would make every other segment narrower.

Claude Code's `statusLine` accepts multi-line output (each `print`/`echo`
is a separate row, per the official docs at
<https://code.claude.com/docs/en/statusline#display-multiple-lines>);
this lets us add identity as a dedicated second line without taking
space away from anything that already works.

## Goal

1. Add an opt-in second line: `⤷ <project> ⎇ <branch>●` (the `●` dot
   appears only when the working tree is dirty).
2. Default off. Opt-in via `show_project_branch: true` in config so
   existing users don't see a sudden taller bar on upgrade.
3. Inline render path stays under its ~30 ms budget. No `git` subprocess
   call on the synchronous render path. Branch comes from reading
   `.git/HEAD` directly (microseconds); dirty comes from a shared cache
   refreshed by a background worker.
4. Outside a git repo, the line collapses to `⤷ <project> (no git)` so
   the identity signal still survives.
5. Works in all three styles (classic, capsule, hairline) and respects
   the active theme.

## Out of scope

- Replacing the existing first line. The first line is unchanged.
- Showing ahead/behind, stash count, remote URL, or commit SHA. Branch
  + dirty is the whole signal.
- Detecting non-git VCS (jj, hg, fossil). Git only.
- Anything beyond `workspace.repo.name` / `.git/HEAD` for repo identity.
  No `origin` URL parsing beyond what Claude Code already gives us in
  stdin.

## Data sources (preferred → fallback)

All these are read **per render** but the slow ones are cached.

| What | Source | Cost per render |
|---|---|---|
| Project name | stdin `workspace.repo.name` → `basename(workspace.project_dir)` → `basename(workspace.current_dir)` → `basename(cwd)` | 0 (already parsed) |
| Inside-worktree flag | stdin `workspace.git_worktree` (string when in linked worktree, absent otherwise) | 0 |
| Resolved git toplevel | walk parents of `workspace.current_dir` until `.git/` exists, then resolve `.git`-as-file `gitdir:` indirection | < 1 ms |
| Current branch | read `<resolved-gitdir>/HEAD` directly. `ref: refs/heads/<name>` → `<name>`. Raw SHA → first 7 chars + dimmed. Unborn branch (HEAD points to ref that doesn't exist on disk yet) → `<name>` still | < 1 ms |
| Dirty | TTL-cached `git status --porcelain` result keyed by `sha1(resolved-toplevel)` | 0 on hit; refresh on miss via background thread (daemon) or detached `Popen` (inline) |

`parse_stdin_data()` in `core.py` gains four lines extracting
`workspace.repo.name`, `workspace.project_dir`, `workspace.current_dir`,
and `workspace.git_worktree`. The new fields default to empty/None when
absent (older Claude Code versions and the no-stdin path both handled
the same way).

## Cache

Path: `~/.cache/claude-statusbar/git/<sha1(toplevel)>.json`. One file
per repo, shared across sessions, shared between inline and daemon.

Contents:

```json
{
  "toplevel": "/absolute/path/to/repo",
  "branch": "main",
  "dirty": false,
  "ts": 1716000000.0
}
```

Behavior:

- **Hit** (`now - ts < 5s` and file readable): use it. No spawn.
- **Stale or missing**: render with the **last known dirty** if any
  (use the file's cached value, just visually mark "old"? No — see
  decision in Risks. We just use the value verbatim until refresh
  lands.). If the file doesn't exist at all, render with no `●` and
  no `○`; the next frame after refresh fills it in.
- **Inflight throttle**: alongside the cache file, an `inflight` marker
  (a sibling file `<sha1>.inflight` containing the spawning pid + ts).
  If the marker exists and is younger than 30 s, do not spawn a second
  refresh. Stale markers (older than 30 s) are ignored and overwritten.
- **Corrupt / unreadable cache file**: treated as cache miss. Never
  raises to the renderer.

### Refresh — inline path

Daemon may not be running. The inline `cs` process renders once and
exits, so it cannot keep a long-lived worker. Pattern:

```python
def _spawn_refresh(toplevel):
    import subprocess  # lazy, only on this branch
    subprocess.Popen(
        ["git", "-C", toplevel, "status", "--porcelain=v1"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,   # captured by helper, see below
        stderr=subprocess.DEVNULL,
        close_fds=True,
        start_new_session=True,
    )
```

…but `Popen` directly with stdout=PIPE leaves the child writing into a
pipe the parent never reads. Instead we use a tiny helper script
shipped in the package (`_git_refresh.py`) that the inline parent
launches via `python -m claude_statusbar._git_refresh <toplevel>
<cache_path>`. The helper does the git call, writes the cache
atomically (`os.replace(tmp, cache_path)`), removes the inflight marker,
and exits. Parent does `Popen(..., start_new_session=True)` and exits
immediately; the OS init reaps the helper.

The lazy `import subprocess` keeps `test_import_perf.py` invariant
("render path must not import subprocess") intact — `subprocess` is
only imported inside the `if cache_is_stale:` branch.

### Refresh — daemon path

The daemon has a 1 s tick loop. Pattern (per codex's recommendation
against fire-and-forget in long-lived processes):

- Per-repo `threading.Lock` in the daemon. When a tick decides the
  cache for repo `R` is stale, daemon submits a job to a small
  `ThreadPoolExecutor(max_workers=4)`.
- The worker calls `subprocess.run(["git", "-C", toplevel, "status",
  "--porcelain=v1"], timeout=2, stdout=PIPE, stderr=DEVNULL)`, writes
  the cache atomically, removes the inflight marker, releases the lock.
- `timeout=2` bounds runaway calls on pathological repos. On timeout
  the cache file is not touched; the next tick will retry.
- Worker exit is awaited by Python's stdlib; no zombies.

The daemon and the inline path share the same cache file; whichever
path runs more often wins, but both paths converge on the same value.

## Render

A new function `render_identity_line(...)` lives in `styles.py`, called
once per render after the main `render_<style>(...)` returns its first
line. The main `format_status_line` (in `progress.py`) joins them with
`\n` when `show_project_branch` is enabled.

Glyph stays the same across all three styles (`⤷` / `⎇` / `●`); the
theme is what changes:

| Token | Color |
|---|---|
| `⤷ ` | `theme.mute` |
| project name | `theme.mute` (subtle — it's identity, not the headline) |
| ` ⎇ ` | `theme.edge` |
| branch | `theme.pill_ink` (the "primary text" tone) |
| `●` dirty | `theme.s_warn` (yellow tone — not alarm; it's normal to have unsaved changes) |
| `(no git)` | `theme.mute` (italic via `\033[3m`) |
| `[worktree: name]` suffix when `workspace.git_worktree` set | `theme.mute` |

Detached HEAD branch is rendered as `theme.mute` italic 7-char SHA to
distinguish from branch names.

## Config

Adds one key to `config.py` defaults:

```python
"show_project_branch": False,
```

Surfaced via:

- `cs config show_project_branch on|off`
- Read by both `core.main()` (inline) and `daemon.py` (daemon tick).

## Failure modes

| Situation | Behavior |
|---|---|
| stdin missing `workspace` entirely | `basename(os.getcwd())` for project; no git ops; show `⤷ <name> (no git)` |
| stdin has `workspace` but no `repo.name` | fallback chain (`project_dir` → `current_dir` → `cwd`) |
| cwd not under a git directory | `⤷ <name> (no git)` |
| `.git/HEAD` unreadable / malformed | `⤷ <name>` only (no `⎇`, no `(no git)`) |
| Relative `gitdir:` in `.git` file | resolved against the containing directory |
| Cache file corrupt / partial JSON | treated as miss; refresh spawns |
| `git status` exits non-zero or times out | cache file not updated; previous value persists until next successful refresh |
| `git` binary not on PATH | refresh helper exits 0 silently; cache stays missing; line renders without dot indefinitely (no error noise) |
| Two simultaneous renders both see stale cache | inflight marker prevents the second spawn |

## Tests

`tests/test_project_branch.py` (new file):

**Must:**

- `.git/HEAD` parser:
  - `ref: refs/heads/main` → `("main", False)` (branch, detached)
  - 40-char SHA → `(sha[:7], True)`
  - `.git` is a file with `gitdir: /abs/path` → follows
  - `.git` is a file with `gitdir: ../relative/path` → resolves against containing dir
  - unborn branch (`ref: refs/heads/new` but file missing) → returns name anyway
- Project name fallback chain: each of the four sources tested by
  removing the higher-priority ones from a fixture stdin payload.
- `workspace` key entirely absent vs `workspace` present but empty —
  both fall through to `cwd` correctly.
- Non-git directory: render produces `⤷ <name> (no git)`, no
  subprocess spawn.
- Cache hit returns instantly without spawning (mocked time).
- Cache miss spawns exactly once even with two concurrent calls
  (inflight lock).
- Stale cache returns the previous value immediately AND triggers a
  refresh (does NOT block on the refresh).
- Clean repo: explicit assertion that `●` is absent.
- Corrupt cache file: treated as miss, no exception.
- `test_import_perf.py` still passes (no top-level `subprocess`
  import in the render hot path).

**Nice-to-have:**

- Daemon integration: spin a real git repo fixture, mutate it, assert
  cache file converges within one tick.
- Worktree fixture: `git worktree add` and assert branch resolution
  follows the gitdir indirection.

## Risks

- **Visual height churn on upgrade.** Mitigated by `default: false`.
  Documented in CHANGELOG and `cs config` help text.
- **Big monorepo `git status` slow.** `timeout=2` in the daemon
  worker bounds worst case. Inline path never blocks on git.
- **Stale dirty for up to 5 s** after a save. Acceptable for a status
  bar; the goal is "did I save?", not millisecond precision.
- **Showing stale value as authoritative.** We render the cached value
  with no "this is stale" indicator. Alternative: dim the `●` while
  inflight is set. Decision: skip — adds two ANSI sequences and the
  user can't tell anyway. If feedback comes in, we add it later.
- **Cache directory growth.** One file per repo path ever opened.
  Negligible (each file is < 100 bytes). No GC needed; if it ever
  matters, `daemon.py`'s existing per-session GC loop can sweep the
  git/ subdir too.
- **PATH-less `git` binary on minimal CI containers.** Refresh helper
  swallows the `FileNotFoundError` and exits 0. Renderer shows no
  dot, no error. (Tested explicitly.)

## Migration

None required. Existing users see no change unless they run
`cs config show_project_branch on`.

## Implementation outline (for the implementation plan)

1. Extend `parse_stdin_data()` to extract the four new `workspace.*`
   fields.
2. New module `claude_statusbar/identity.py` containing
   `resolve_identity(stdin_data) -> IdentityInfo` (project + branch +
   dirty + worktree-name).
3. New module `claude_statusbar/_git_refresh.py` — the detached refresh
   helper invoked by inline.
4. Extend `styles.py` with `render_identity_line(info, theme)`.
5. Extend `format_status_line` in `progress.py` to optionally append
   the identity line.
6. Extend `daemon.py` tick with a small `ThreadPoolExecutor` for
   per-repo refresh.
7. Extend `config.py` defaults + `cli.py` `cs config` handler.
8. New test file as above. Adjust `test_import_perf.py` only if a new
   top-level import sneaks in (it shouldn't).
9. CHANGELOG entry + README section.
