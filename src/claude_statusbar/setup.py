#!/usr/bin/env python3
"""Auto-repair and setup utilities for claude-statusbar.

Ensures ~/.claude/settings.json always has a working statusLine pointing at
the `cs` CLI, and copies bundled slash commands into ~/.claude/commands/.

First-install reliability is the priority here: write atomically, prefer the
absolute path of `cs` when we can find it (so it survives PATH gaps that
GUI-launched Claude Code sees), and refresh stale configs from prior
installs.
"""

import json
import os
import shlex
import shutil
import sys
from pathlib import Path, PureWindowsPath
from typing import Optional, Tuple

from .cache import atomic_write_text

SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
COMMANDS_DIR  = Path.home() / ".claude" / "commands"
SKILLS_DIR    = Path.home() / ".claude" / "skills"

# CLI binary names we ship — `cs` is shortest and the documented one.
OUR_COMMAND_NAMES = ("cs", "cstatus", "claude-statusbar")

# Launcher shims pip/pipx create on Windows around our entry points.
# shutil.which can also return uppercase extensions there ("cs.EXE"),
# so matching must lowercase first (see _normalize_command_name).
_WINDOWS_SHIM_EXTENSIONS = (".exe", ".cmd", ".bat")


def _normalize_command_name(name: str) -> str:
    """Normalize a binary basename for matching against OUR_COMMAND_NAMES.

    On Windows, shutil.which("cs") resolves to "...\\cs.EXE" and pip writes
    "cs.exe"/"cs.cmd" shims — an exact match against "cs" would then fail,
    making doctor report "(not ours)" and --setup refuse to touch a
    perfectly valid entry (issue #32). Lowercase and strip the known shim
    extension before comparing.
    """
    name = name.lower()
    for ext in _WINDOWS_SHIM_EXTENSIONS:
        if name.endswith(ext):
            return name[: -len(ext)]
    return name


def _is_windows() -> bool:
    """Module-level so tests can monkeypatch the platform."""
    return os.name == "nt"


def _shell_path(p: str) -> str:
    """Make a path safe to embed in the statusLine command string.

    Claude Code executes that string through a POSIX shell (Git Bash on
    Windows), where `\\` is an escape character: `C:\\Users\\me\\cs.EXE`
    execs as `C:Usersmecs.EXE` and dies with exit 127 even though the file
    exists (issue #42). Forward slashes work in every shell involved —
    sh, and cmd.exe too for full paths.

    Quoting uses double quotes, not shlex.quote: shlex emits single quotes,
    which sh honors but cmd.exe does not treat as quoting at all.
    """
    if "\\" in p:
        p = PureWindowsPath(p).as_posix()
    if " " in p:
        return f'"{p}"'
    return p


def _command_tokens(cmd: str) -> list:
    """Tokenize a statusLine command without destroying Windows paths.

    shlex.split(posix=True) treats `\\` as an escape — the exact mangling
    this module exists to prevent — so a poisoned `C:\\Users\\me\\cs.EXE`
    entry would tokenize to garbage, read as foreign, and be exempted from
    healing. Non-posix mode preserves backslashes but leaves quote marks
    attached to tokens; strip those.
    """
    try:
        tokens = shlex.split(cmd.strip(), posix=False)
    except ValueError:  # unbalanced quotes — degrade to whitespace split
        tokens = cmd.strip().split()
    return [t.strip('"\'') for t in tokens]


def _split_command(cmd: str) -> Tuple[str, str]:
    """Split into (executable token, verbatim tail).

    The tail keeps its original spacing and quoting so a repair can replace
    only the executable and re-attach user-added flags untouched.
    """
    s = cmd.strip()
    try:
        raw = shlex.split(s, posix=False)
    except ValueError:
        raw = s.split()
    if not raw:
        return "", ""
    return raw[0].strip('"\''), s[len(raw[0]):]


def _resolve_cs_command() -> str:
    """Best-effort absolute path to our `cs` binary.

    Falls back to the bare name `cs` so `command not found` is at least
    visible to the user when they restart Claude Code.

    Resolution order:
      1. shutil.which("cs") — honors current PATH
      2. The script that's running us (sys.argv[0]) if it ends with cs/cstatus/...
      3. Common install locations probed in order
      4. Bare "cs"
    """
    cmd = shutil.which("cs") or shutil.which("cstatus") or shutil.which("claude-statusbar")
    if cmd and Path(cmd).is_file():
        return cmd

    # If we're being invoked as `python -m claude_statusbar`, sys.argv[0] is the script
    argv0 = Path(sys.argv[0]) if sys.argv and sys.argv[0] else None
    if argv0 and argv0.is_file() and _normalize_command_name(argv0.name) in OUR_COMMAND_NAMES:
        return str(argv0.resolve())

    for p in (
        Path.home() / ".local" / "bin" / "cs",
        Path.home() / ".local" / "share" / "uv" / "tools" / "claude-statusbar" / "bin" / "cs",
        Path.home() / ".local" / "pipx" / "venvs" / "claude-statusbar" / "bin" / "cs",
        Path("/usr/local/bin/cs"),
        Path("/opt/homebrew/bin/cs"),
    ):
        if p.is_file():
            return str(p)

    return "cs"


# Default refresh interval. 1 second so the cache-age countdown actually
# ticks visibly out of the box. At inline cost (~30ms/render) that's ~3%
# CPU; users who care about that overhead should pair with `--fast`
# (daemon mode brings it under 1%).
DEFAULT_REFRESH_INTERVAL = 1


def _statusline_config(fast: bool = False, refresh_interval: int = DEFAULT_REFRESH_INTERVAL) -> dict:
    """Build the statusLine entry we want to write.

    `fast=True` emits ``cs render`` (Phase B daemon thin client). The bare
    ``cs`` form keeps the legacy inline path so existing users aren't
    affected by this change.

    `refresh_interval` is written into settings.json so the cache-age
    countdown actually animates. Without it, Claude Code only re-renders
    on activity (turn complete, tool use), and time-based segments freeze.
    """
    cmd = _shell_path(_resolve_cs_command())
    if fast:
        cmd = f"{cmd} render"
    return {
        "type": "command",
        "command": cmd,
        "refreshInterval": refresh_interval,
    }


def _invokes_our_module(cmd: str) -> bool:
    """True for ``<python> -m claude_statusbar.cli render``.

    A legitimate way to run us that skips pip's console-script launcher. On
    Windows that launcher spawns a second process, roughly doubling status-line
    latency (~0.9s vs ~0.44s per render on a conda install), so users on slow
    Python startups may prefer the module form. Recognise it as ours rather
    than reporting it as a foreign tool.
    """
    return "claude_statusbar" in cmd


def _is_our_statusline(entry: object) -> bool:
    """Return True if the existing statusLine entry already points at our CLI."""
    if not isinstance(entry, dict):
        return False
    cmd = entry.get("command")
    if not isinstance(cmd, str) or not cmd.strip():
        return False
    if _invokes_our_module(cmd):
        return True
    tokens = _command_tokens(cmd)
    if not tokens:
        return False
    # PureWindowsPath understands both separators, so a backslash entry is
    # recognized as ours on any platform — it has to be, or the daily heal
    # would treat a poisoned Windows entry as foreign and never fix it.
    try:
        name = _normalize_command_name(PureWindowsPath(tokens[0]).name)
    except ValueError:
        return False
    return name in OUR_COMMAND_NAMES


def _read_settings() -> dict:
    if not SETTINGS_PATH.exists():
        return {}
    try:
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_settings(data: dict) -> bool:
    """Atomically write settings.json so we can never leave half a file behind."""
    return atomic_write_text(
        SETTINGS_PATH,
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
    )


def is_statusline_configured() -> bool:
    """Return True if settings.json already has *our* statusLine entry."""
    settings = _read_settings()
    return _is_our_statusline(settings.get("statusLine"))


def _existing_uses_render(existing) -> bool:
    """True if the user's current statusLine command is `cs render`-style.

    Used by the daily auto-repair path to preserve the user's choice of fast
    vs inline mode — without this check we'd silently downgrade a fast-mode
    user back to bare `cs` because `_statusline_config()` defaults to
    fast=False.
    """
    if not isinstance(existing, dict):
        return False
    cmd = existing.get("command")
    if not isinstance(cmd, str):
        return False
    parts = _command_tokens(cmd)
    # `cs render`, and the module form `<python> -m claude_statusbar.cli render`
    # — in both, `render` is the last token.
    return len(parts) >= 2 and parts[-1] == "render"


def _repair_command(cmd: str) -> Optional[str]:
    """Return a repaired command string, or None when `cmd` is healthy.

    Used by the daily self-heal for entries that are already ours. Drift is
    defined as *broken*, not *different from today's canonical form* — the
    old string-equality check reverted any Windows hand-fix back to a
    backslash path every 24h (issue #42) and silently stripped user-added
    CLI flags. A repair only ever replaces the executable token; the
    argument tail survives verbatim.

    Broken means one of:
      - Windows + backslashes in the executable: the file may exist, but
        Claude Code runs the string through Git Bash's sh, where `\\` is an
        escape — shell-dead despite Path(...).is_file() saying healthy, so
        this check must come before any filesystem probe.
      - bare name (`cs`): works in a terminal, but GUI-launched Claude Code
        often has a narrower PATH — upgrade to the absolute path.
      - the executable path no longer exists (moved/reinstalled elsewhere).
    """
    tok0, tail = _split_command(cmd)
    if not tok0:
        return None

    if _is_windows() and "\\" in tok0:
        healed = PureWindowsPath(tok0).as_posix()
        if Path(healed).is_file():
            return _shell_path(healed) + tail
        if _invokes_our_module(cmd):
            # A module-form command cannot be safely replaced with the `cs`
            # console script, but its interpreter still needs shell-safe
            # separators. Keep `-m claude_statusbar...` and every argument.
            return _shell_path(healed) + tail
        tok0 = healed  # separators fixed but target gone too — re-resolve below

    if _invokes_our_module(cmd):
        # Deliberate user choice (see _invokes_our_module) — never rewritten.
        return None

    if "/" not in tok0 and "\\" not in tok0:
        candidate = _shell_path(_resolve_cs_command())
        if candidate.strip('"') == tok0:
            return None  # resolver found nothing better than the bare name
        return candidate + tail

    if not Path(tok0).is_file():
        # Trust the resolver here: it already verified its non-fallback
        # candidates, and second-guessing it would leave dead entries dead.
        candidate = _shell_path(_resolve_cs_command())
        if candidate.strip('"') == tok0:
            return None
        return candidate + tail

    return None


def ensure_statusline_configured(fast: Optional[bool] = None) -> Tuple[bool, str]:
    """Silently ensure settings.json has *our* statusLine config.

    `fast` is tri-state:
      - ``None``  (default): preserve the user's existing fast/inline choice;
        for fresh writes (no statusLine yet), use daemon mode (the 3.6.0
        default). This is what the daily auto-repair path passes — it
        should never make a policy decision on the user's behalf.
      - ``True``: force daemon mode (``cs render``). Used when the user runs
        ``cs --setup`` (3.6.0 default) or the explicit ``cs --setup --fast``.
      - ``False``: force inline mode. Used when the user runs
        ``cs --setup --inline`` to opt out.

    Behavior:
      - missing       → write our config (fast=True if None, else honors arg)
      - foreign cmd   → leave alone (don't overwrite another tool's setup)
      - our cmd       → refresh path; ``fast=None`` preserves existing,
                        ``fast=True/False`` forces the write.

    Returns (changed, message).
    """
    settings = _read_settings()
    existing = settings.get("statusLine")

    if existing is None:
        # Fresh install: default to fast/daemon since 3.6.0.
        write_fast = True if fast is None else fast
        desired = _statusline_config(fast=write_fast)
        settings["statusLine"] = desired
        if _write_settings(settings):
            return True, f"Added statusLine config to {SETTINGS_PATH}"
        return False, f"Could not write to {SETTINGS_PATH}"

    if not _is_our_statusline(existing):
        # Don't trample another tool's statusLine.
        cmd = existing.get("command", "?") if isinstance(existing, dict) else "?"
        return False, (
            f"settings.json already has a different statusLine command "
            f"({cmd!r}). Leaving it alone — set "
            f'"statusLine": {{"type": "command", "command": "cs"}} '
            f"manually if you want claude-statusbar."
        )

    # Ours already.
    if fast is None:
        # Daily self-heal: repair only what is broken, never churn what
        # merely differs from today's canonical form (fast/inline choice,
        # user-added flags, hand-fixed separators all survive — issue #42).
        changed = False
        existing_cmd = existing.get("command")
        if isinstance(existing_cmd, str):
            repaired = _repair_command(existing_cmd)
            if repaired is not None and repaired != existing_cmd:
                existing["command"] = repaired
                changed = True
        existing_refresh = existing.get("refreshInterval")
        if not (isinstance(existing_refresh, (int, float)) and existing_refresh > 0):
            existing["refreshInterval"] = DEFAULT_REFRESH_INTERVAL
            changed = True
        if not changed:
            return False, "statusLine already configured"
        settings["statusLine"] = existing
        if _write_settings(settings):
            return True, (
                f"Refreshed statusLine command to "
                f"{existing.get('command')!r} in {SETTINGS_PATH}"
            )
        return False, f"Could not write to {SETTINGS_PATH}"

    # Explicit `cs --setup [--fast|--inline]`: the user asked for a rewrite,
    # so force the canonical form. This is the one path allowed to drop
    # custom flags — an explicit request, unlike the daily pass above.
    existing_refresh = existing.get("refreshInterval")
    if isinstance(existing_refresh, (int, float)) and existing_refresh > 0:
        effective_refresh = int(existing_refresh)
    else:
        effective_refresh = DEFAULT_REFRESH_INTERVAL
    desired = _statusline_config(fast=fast, refresh_interval=effective_refresh)

    # The module form is a deliberate choice (see `_invokes_our_module`), not
    # drift — even an explicit setup must not rewrite it back to the console
    # script. Keep the command, still refresh refreshInterval.
    existing_cmd = existing.get("command")
    if isinstance(existing_cmd, str) and _invokes_our_module(existing_cmd):
        desired["command"] = existing_cmd

    if (existing.get("command") != desired["command"]
            or existing.get("refreshInterval") != desired["refreshInterval"]):
        settings["statusLine"] = desired
        if _write_settings(settings):
            return True, (
                f"Refreshed statusLine command path to "
                f"{desired['command']!r} in {SETTINGS_PATH}"
            )
        return False, f"Could not write to {SETTINGS_PATH}"

    return False, "statusLine already configured"


def project_settings_path(project_dir: Path) -> Path:
    """Where Claude Code looks for a project-level statusLine override."""
    return project_dir / ".claude" / "settings.json"


def ensure_project_statusline_configured(
    project_dir: Path,
    fast: bool = True,
    refresh_interval: int = DEFAULT_REFRESH_INTERVAL,
) -> Tuple[bool, str]:
    """Write a project-level .claude/settings.json so that this project's
    statusLine survives even when another tool reclaims the user-level
    ~/.claude/settings.json slot.

    Behavior:
      - project_dir missing → error.
      - .claude/settings.json missing → write a new one with statusLine only.
      - file exists, no statusLine → merge our statusLine in, keep other keys.
      - statusLine already ours → idempotent (refresh path/refreshInterval if drifted).
      - statusLine is a foreign command → leave alone (don't trample).

    Returns (changed, message).
    """
    try:
        project_dir = Path(project_dir).expanduser().resolve()
    except (OSError, RuntimeError) as e:
        return False, f"Could not resolve project path: {e}"
    if not project_dir.is_dir():
        return False, f"Project directory not found: {project_dir}"

    path = project_settings_path(project_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return False, f"Could not create {path.parent}: {e}"

    if path.exists():
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as e:
            # File is there but we can't read it — most likely permission
            # denied. Bail without writing, otherwise atomic_write_text
            # would clobber a file we couldn't inspect.
            return False, f"Could not read {path}: {e}"
        try:
            existing_data = json.loads(raw)
            if not isinstance(existing_data, dict):
                existing_data = {}
        except json.JSONDecodeError:
            # Corrupt JSON: treated as empty so the next write resets the file.
            existing_data = {}
    else:
        existing_data = {}

    existing_sl = existing_data.get("statusLine")
    if (existing_sl is not None
            and isinstance(existing_sl, dict)
            and not _is_our_statusline(existing_sl)):
        cmd = existing_sl.get("command", "?")
        return False, (
            f"{path} already has a non-cs statusLine ({cmd!r}). "
            f"Edit it manually if you want cs there."
        )

    desired = _statusline_config(fast=fast, refresh_interval=refresh_interval)
    if existing_sl == desired:
        return False, f"statusLine already configured at {path}"

    existing_data["statusLine"] = desired
    if atomic_write_text(
        path,
        json.dumps(existing_data, indent=2, ensure_ascii=False) + "\n",
    ):
        return True, f"Wrote project statusLine to {path}"
    return False, f"Could not write to {path}"


def _packaged_commands_dir() -> Path:
    """Return the directory bundled with the package that holds slash commands."""
    here = Path(__file__).resolve()
    return here.parent / "commands"


def _packaged_skills_dir() -> Path:
    """Return the directory bundled with the package that holds skill files."""
    here = Path(__file__).resolve()
    return here.parent / "skills"


def install_commands(force: bool = False) -> Tuple[int, list, list]:
    """Copy bundled slash commands into ~/.claude/commands/.

    Returns (count_installed, skipped, failed).

    The two lists mean very different things and must not be conflated:

    - `skipped` — the file exists with content the user changed, so we leave it
      alone. Entirely benign, and re-running the installer (the documented
      upgrade path) hits it every time. Must never make the exit code non-zero.
    - `failed` — we tried to write and could not. A real problem.
    """
    src_dir = _packaged_commands_dir()
    if not src_dir.is_dir():
        return 0, [], []

    COMMANDS_DIR.mkdir(parents=True, exist_ok=True)
    installed = 0
    skipped: list = []
    failed: list = []

    for src in sorted(src_dir.glob("*.md")):
        name = src.name
        dst = COMMANDS_DIR / name
        if dst.exists() and not force:
            try:
                if dst.read_text(encoding="utf-8") == src.read_text(encoding="utf-8"):
                    installed += 1
                    continue
            except OSError:
                pass
            skipped.append(str(dst))
            continue
        try:
            shutil.copy2(src, dst)
            installed += 1
        except OSError as e:
            failed.append(f"{dst}: {e}")
    return installed, skipped, failed


def install_skills(force: bool = False) -> Tuple[int, list, list]:
    """Copy bundled skills into ~/.claude/skills/<skill-name>/SKILL.md.

    Each skill lives in its own directory (per Claude Code skill convention).
    Returns (count_installed, skipped, failed) — see install_commands() for
    why a user-modified file (skipped) must not be treated as a failure.
    """
    src_dir = _packaged_skills_dir()
    if not src_dir.is_dir():
        return 0, [], []

    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    installed = 0
    skipped: list = []
    failed: list = []

    for skill_dir in sorted(src_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        src = skill_dir / "SKILL.md"
        if not src.is_file():
            continue
        dst_dir = SKILLS_DIR / skill_dir.name
        dst = dst_dir / "SKILL.md"
        dst_dir.mkdir(parents=True, exist_ok=True)
        if dst.exists() and not force:
            try:
                if dst.read_text(encoding="utf-8") == src.read_text(encoding="utf-8"):
                    installed += 1
                    continue
            except OSError:
                pass
            skipped.append(str(dst))
            continue
        try:
            shutil.copy2(src, dst)
            installed += 1
        except OSError as e:
            failed.append(f"{dst}: {e}")
    return installed, skipped, failed


def run_setup(verbose: bool = True, install_cmds: bool = True, fast: bool = True) -> int:
    """Interactive setup: configure the statusLine and install slash commands.

    `fast=True` (default since 3.6.0) installs Phase B daemon mode: statusLine
    command becomes ``cs render``, backed by a long-lived daemon. Each tick is
    ~3-5ms vs ~30ms inline, which keeps continuous CPU under 1% at
    refreshInterval=1 (vs ~3% in inline mode). Pass ``fast=False`` to opt back
    into the legacy inline path.

    Returns exit code (0 success, 1 partial failure, 2 unrecoverable).
    """
    changed, message = ensure_statusline_configured(fast=fast)
    statusline_ok = changed or "already configured" in message

    if verbose:
        marker = "✓" if statusline_ok else "!"
        print(f"{marker} {message}")
        if changed:
            print("  Restart Claude Code for the status bar to appear.")
        else:
            print(f"  Settings file: {SETTINGS_PATH}")

    cmds_ok = True
    if install_cmds:
        n, skipped, failed = install_commands()
        # Compute status OUTSIDE the verbose blocks: the exit code must describe
        # what happened, not how loudly we described it. (It used to be set only
        # under `if verbose`, so the same run returned 0 quietly and 1 verbosely.)
        # A user-modified file we deliberately left alone is not a failure —
        # re-running install.sh, the documented upgrade path, hits that every
        # time and used to print a spurious "cs --setup reported an issue".
        cmds_ok = not failed
        if verbose:
            if n:
                print(f"✓ Installed {n} slash command(s) to {COMMANDS_DIR}")
            if skipped:
                print(f"  Kept your edited version (use --force to overwrite):")
                for s in skipped:
                    print(f"    {s}")
            if failed:
                print(f"! Could not install:")
                for s in failed:
                    print(f"    {s}")
            print("  Try /statusbar in Claude Code.")

        # Install the consolidated skill alongside the slash commands.
        s_n, s_skipped, s_failed = install_skills()
        if s_failed:
            cmds_ok = False
        if verbose:
            if s_n:
                print(f"✓ Installed {s_n} skill(s) to {SKILLS_DIR}")
            if s_skipped:
                print(f"  Kept your edited skill (use --force to overwrite):")
                for s in s_skipped:
                    print(f"    {s}")
            if s_failed:
                print(f"! Could not install skill:")
                for s in s_failed:
                    print(f"    {s}")

    if fast:
        # Spin up the daemon now so the next status-line tick benefits.
        # Failure isn't fatal — render_thin will lazy-spawn anyway.
        try:
            from . import daemon as _d
            rc = _d.cmd_start(detach=True)
            if verbose and rc == 0:
                print("✓ Daemon started — status bar renders should be ~5ms each tick.")
        except Exception as e:
            if verbose:
                print(f"! Could not pre-start daemon: {e} (lazy-spawn will retry)")

    if statusline_ok and cmds_ok:
        return 0
    if statusline_ok or cmds_ok:
        return 1
    return 2
