#!/usr/bin/env python3
"""
Auto-updater for claude-statusbar
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional, Tuple

import importlib.metadata as metadata

# Distribution name on PyPI (used for local version lookup)
DIST_NAME = "claude-statusbar"
PYPI_URL = "https://pypi.org/pypi/claude-statusbar/json"
# One-liner that re-installs the standalone binary from the latest GitHub Release.
GITHUB_REPO = "leeguooooo/claude-code-usage-bar"
INSTALL_SH_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/install.sh"
BINARY_UPGRADE_HINT = f"curl -fsSL {INSTALL_SH_URL} | bash"


def _is_frozen() -> bool:
    """True when running as a PyInstaller standalone binary (no pip/uv around).

    Frozen binaries can't `pip install --upgrade` themselves — `sys.executable`
    is the binary, not a Python — so the upgrade path re-runs install.sh instead.
    """
    return bool(getattr(sys, "frozen", False))
# The background check writes the latest PyPI version here; the render path
# reads it (cheap, no network) to show a `↑<newver>` update hint on the bar.
LATEST_VERSION_CACHE = Path.home() / ".cache" / "claude-statusbar" / "latest_version.json"


def _cache_latest_version(version: str) -> None:
    """Persist the latest-known PyPI version for the render path to read."""
    try:
        import time
        from .cache import atomic_write_text
        LATEST_VERSION_CACHE.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            LATEST_VERSION_CACHE,
            json.dumps({"version": str(version), "checked_at": time.time()}),
        )
    except Exception:
        pass


def get_current_version() -> str:
    """Best-effort local installed version."""
    try:
        return metadata.version(DIST_NAME)
    except metadata.PackageNotFoundError:
        # Running from source without an installed distribution.
        return "0.0.0"


def get_latest_version() -> Optional[str]:
    """Get latest version from PyPI"""
    try:
        # Cache-buster: pypi.org/pypi/<pkg>/json sits behind a CDN whose edge
        # nodes can serve a stale `info.version` for minutes after a release —
        # long enough for `cs upgrade`, run right after publishing, to report
        # the version it just replaced. A varying query string misses the edge
        # cache and asks the origin.
        import time as _t
        url = f"{PYPI_URL}?t={int(_t.time())}"
        with urllib.request.urlopen(url, timeout=5) as response:
            data = json.loads(response.read().decode())
            latest = data["info"]["version"]
            _cache_latest_version(latest)
            return latest
    except (urllib.error.URLError, json.JSONDecodeError, KeyError):
        return None


GITHUB_LATEST_RELEASE_URL = (
    f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
)


def latest_release_tag() -> Optional[str]:
    """Newest published GitHub Release version, or None.

    The standalone binary is downloaded from GitHub Releases, so GitHub is the
    authority on whether it is current. Asking PyPI was asking the wrong
    service: its JSON index updates asynchronously after an upload, so for a
    minute or two after every release `cs upgrade` answered with the version
    it had just replaced — five times in one afternoon.
    """
    try:
        req = urllib.request.Request(
            GITHUB_LATEST_RELEASE_URL,
            headers={"Accept": "application/vnd.github+json",
                     "User-Agent": f"claude-statusbar/{get_current_version()}"},
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            tag = str(json.loads(response.read().decode())["tag_name"])
        return tag.lstrip("v") or None
    except (urllib.error.URLError, json.JSONDecodeError, KeyError, TimeoutError):
        return None


def resolve_latest_version() -> Optional[str]:
    """The newest version available *through this install's own channel*.

    Frozen binaries come from GitHub Releases; everything else from PyPI.
    Falls back to the other source rather than reporting nothing at all.
    """
    if _is_frozen():
        return latest_release_tag() or get_latest_version()
    return get_latest_version()


def compare_versions(current: str, latest: str) -> bool:
    """Compare versions (True if latest > current)"""
    try:

        def to_int_parts(v: str) -> list[int]:
            parts: list[int] = []
            for chunk in v.split("."):
                digits = ""
                for ch in chunk:
                    if ch.isdigit():
                        digits += ch
                    else:
                        break
                parts.append(int(digits or 0))
            return parts

        current_parts = to_int_parts(current)
        latest_parts = to_int_parts(latest)

        # Pad shorter version with zeros
        max_len = max(len(current_parts), len(latest_parts))
        current_parts.extend([0] * (max_len - len(current_parts)))
        latest_parts.extend([0] * (max_len - len(latest_parts)))

        return latest_parts > current_parts
    except (ValueError, AttributeError):
        return False


def detect_install_channel(
    executable: str | Path | None = None,
) -> str:
    """Infer how claude-statusbar is currently installed."""
    raw = Path(executable or sys.executable).expanduser()
    candidates = [raw]
    if executable is None:
        candidates.append(Path(sys.prefix).expanduser())
    try:
        candidates.append(raw.resolve())
    except OSError:
        pass

    for path in candidates:
        parts = path.parts
        if "uv" in parts and "tools" in parts and DIST_NAME in parts:
            return "uv"

        if "pipx" in parts and "venvs" in parts and DIST_NAME in parts:
            return "pipx"

    return "pip"


# Where uv/pipx actually live when they're not on PATH. The daemon often runs
# under launchd/systemd, whose PATH is the bare system default — `~/.local/bin`
# (uv, pipx) and Homebrew are not on it. `shutil.which` alone therefore made
# the daemon's auto-upgrade fall through to `python -m pip` — and a uv tool
# venv ships WITHOUT pip, so the upgrade failed silently, forever.
_TOOL_DIRS = (
    Path.home() / ".local" / "bin",
    Path.home() / ".cargo" / "bin",
    Path("/opt/homebrew/bin"),
    Path("/usr/local/bin"),
)


def _find_tool(name: str) -> Optional[str]:
    """Absolute path to `name`, searching PATH first, then well-known dirs."""
    found = shutil.which(name)
    if found:
        return found
    exe = f"{name}.exe" if sys.platform == "win32" else name
    for d in _TOOL_DIRS:
        cand = d / exe
        if cand.is_file():
            return str(cand)
    return None


def path_entrypoint() -> Optional[Path]:
    """Where `cs` on PATH actually lives, fully resolved. None if absent."""
    found = shutil.which("cs") or shutil.which(DIST_NAME)
    if not found:
        return None
    try:
        return Path(found).resolve()
    except OSError:
        return None


def is_shadow_install() -> bool:
    """True when the `cs` on PATH belongs to a *different* installation.

    Duplicate installs share one entry point: `~/.local/bin/cs`. A leftover
    `uv tool install claude-statusbar` sitting behind a binary install is
    harmless right up until it upgrades itself — uv then rewrites that shared
    symlink to its own copy, and the install the user actually runs is
    silently replaced. Observed live, twice: a stale uv 3.32.0 auto-upgraded
    and took the entry point away from the standalone binary.

    So a copy that doesn't own the entry point must never auto-upgrade: it
    would be upgrading itself *into someone else's install*.
    """
    entry = path_entrypoint()
    if entry is None:
        return False  # nothing on PATH to shadow
    # Compare bin DIRECTORIES, resolving the directory rather than the
    # interpreter file. In a uv-tool / venv install `bin/python3` is a symlink
    # to the base interpreter (e.g. Homebrew's Cellar), so resolving the file
    # lands outside the venv and every such install misreads as a shadow —
    # auto-upgrade then never runs (observed: 3.13.6 stuck for 3 months with
    # auto_upgrade on). The real shadow case — `cs` on PATH living in a
    # different install's bin — still differs after this change.
    try:
        here = Path(sys.executable).parent.resolve()
    except OSError:
        return False
    return entry.parent != here


def find_duplicate_installs() -> list:
    """Every claude-statusbar installation we can see on this machine.

    They all compete for one `cs` on PATH, so more than one is a latent
    takeover: the next auto-upgrade of any of them rewrites the shared symlink
    to itself.
    """
    found = []
    binary_dir = Path.home() / ".local" / "lib" / "claude-statusbar" / "current"
    if binary_dir.exists():
        found.append(f"standalone binary ({binary_dir})")
    uv_dir = Path.home() / ".local" / "share" / "uv" / "tools" / DIST_NAME
    if uv_dir.is_dir():
        found.append(f"uv tool ({uv_dir})")
    pipx_dir = Path.home() / ".local" / "pipx" / "venvs" / DIST_NAME
    if pipx_dir.is_dir():
        found.append(f"pipx ({pipx_dir})")
    return found


def get_upgrade_command(
    executable: str | Path | None = None,
) -> list[str]:
    """Return the most appropriate self-upgrade command for this install."""
    if _is_frozen():
        # Standalone binary: re-run the installer, which pulls the latest
        # release binary for this platform.
        return ["sh", "-c", BINARY_UPGRADE_HINT]

    channel = detect_install_channel(executable)

    if channel == "uv":
        uv = _find_tool("uv")
        if uv:
            return [uv, "tool", "install", "--upgrade", DIST_NAME]

    if channel == "pipx":
        pipx = _find_tool("pipx")
        if pipx:
            return [pipx, "upgrade", DIST_NAME]

    return [sys.executable, "-m", "pip", "install", "--upgrade", DIST_NAME]


# Hard cap so a hung pip/uv install can NEVER freeze a Claude Code statusLine
# render. 60s is generous for fast networks and short-circuits cleanly on slow
# ones — the user gets a normal status line at the next session.
_UPGRADE_TIMEOUT_S = 60


def _run_upgrade(cmd) -> bool:
    """Run an upgrade command with a timeout. Returns True on success."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_UPGRADE_TIMEOUT_S,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        logging.error(f"Upgrade command {cmd!r} failed: {e}")
        return False


# The installer downloads a ~10-25 MB release asset; the 60s cap that suits a
# pip/uv upgrade is too tight for it on a slow link.
_INSTALLER_TIMEOUT_S = 600


def _run_installer(version: Optional[str] = None) -> bool:
    """Run install.sh, letting its output through so the user watches it work.

    Pins the download to `version`'s own tag rather than trusting
    `releases/latest/download`: that pointer lags for a while after a release,
    and the installer never checks that what it fetched is what was asked for.
    Observed: an upgrade to 3.35.3 quietly re-installed 3.35.2 and reported
    success. The installer already honors CS_RELEASE_BASE_URL.

    Only ever called from an explicit `cs upgrade` — never unattended.
    """
    import os
    env = dict(os.environ)
    if _is_frozen():
        # The installer prunes old bundle dirs, and during an unattended
        # upgrade *this* process is executing out of one of them. A PyInstaller
        # onedir binary dlopens its libraries lazily, so deleting that dir
        # mid-run can kill the upgrade it is performing. Tell the installer to
        # spare it; the next upgrade prunes it once nothing is inside.
        env["CS_KEEP_BUNDLE_DIR"] = str(Path(sys.executable).resolve().parent)
    if version:
        env["CS_RELEASE_BASE_URL"] = (
            f"https://github.com/{GITHUB_REPO}/releases/download/v{version}"
        )
    try:
        result = subprocess.run(
            ["sh", "-c", BINARY_UPGRADE_HINT],
            timeout=_INSTALLER_TIMEOUT_S,
            env=env,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        logging.error(f"binary installer failed: {e}")
        return False


def installed_version_on_path() -> Optional[str]:
    """The version of the `cs` that PATH resolves to, by asking it.

    The running process can't report this after an upgrade — it is still the
    old binary in memory. Asking the installed one is the only way to know
    what actually landed.
    """
    entry = path_entrypoint()
    if entry is None:
        return None
    try:
        out = subprocess.run([str(entry), "--version"], capture_output=True,
                             text=True, timeout=15)
    except (subprocess.TimeoutExpired, OSError):
        return None
    parts = (out.stdout or out.stderr).strip().split()
    return parts[-1] if parts else None


def auto_upgrade() -> bool:
    """Attempt automatic upgrade. Bounded by _UPGRADE_TIMEOUT_S per attempt."""
    if is_shadow_install():
        # Upgrading would relink the shared `cs` entry point to this copy,
        # replacing whatever install the user actually uses. Never behind
        # their back; an explicit `cs upgrade` still works.
        logging.info("skipping auto-upgrade: not the install that owns `cs`")
        return False

    if _is_frozen():
        # Binary installs auto-upgrade too (opt out with
        # CLAUDE_STATUSBAR_NO_UPDATE=1 or `cs config set auto_upgrade false`).
        # The installer is pinned to the version we resolved and the result is
        # verified, so an unattended run can't quietly leave a different build
        # behind — the failure mode that made this path suspect to begin with.
        latest = resolve_latest_version()
        if latest is None or not compare_versions(get_current_version(), latest):
            return False
        if not _run_installer(latest):
            return False
        return installed_version_on_path() == latest

    if _run_upgrade(get_upgrade_command()):
        return True

    pipx = _find_tool("pipx")
    if pipx:
        if _run_upgrade([pipx, "upgrade", DIST_NAME]):
            return True

    return _run_upgrade(
        [sys.executable, "-m", "pip", "install", "--upgrade", DIST_NAME]
    )


def upgrade_current_install() -> Tuple[bool, str]:
    """Upgrade the environment that is actually running this CLI."""
    current = get_current_version()

    if _is_frozen():
        latest = resolve_latest_version()
        if latest is None:
            # A check that never completed is not "up to date" — saying so
            # hides exactly the case the user ran this command to find out.
            return False, (
                f"Standalone binary v{current} — could not reach GitHub or "
                f"PyPI to check for updates (network or TLS failure).\n"
                f"Update manually with:\n  {BINARY_UPGRADE_HINT}"
            )
        if not compare_versions(current, latest):
            return True, (
                f"Standalone binary v{current} is the latest "
                f"(per GitHub Releases)."
            )

        # Do the upgrade. Running the installer is what `cs upgrade` means;
        # printing the command and calling it a day was a command that named
        # an action it didn't perform. `auto_upgrade` still refuses to touch a
        # frozen install — that one runs unattended, and *that* is the case
        # "never pipe curl|sh behind the user's back" was written for.
        print(f"Upgrading the standalone binary v{current} → v{latest}...")
        if not _run_installer(latest):
            return False, (
                f"Upgrade to v{latest} failed. Run it manually to see why:\n"
                f"  {BINARY_UPGRADE_HINT}"
            )
        # Verify rather than announce. The installer exiting 0 only means it
        # installed *something* — it once installed the version we were
        # upgrading away from, and this line claimed success anyway.
        landed = installed_version_on_path()
        if landed is None:
            return True, (
                f"Ran the installer for v{latest}, but could not read the "
                f"installed version back. Check `cs --version`."
            )
        if landed != latest:
            return False, (
                f"Asked for v{latest} but v{landed} is what installed. "
                f"The release assets may still be publishing — try again in "
                f"a minute."
            )
        return True, (
            # No restart needed: Claude Code spawns `cs render` fresh every
            # statusline tick, so the replaced binary is live within ~1s.
            f"Upgraded the standalone binary to v{landed}. "
            f"Live on the next statusline tick — no restart needed."
        )

    cmd = get_upgrade_command()

    if _run_upgrade(cmd):
        refreshed = get_current_version()
        return True, f"Upgraded {DIST_NAME} from v{current} to v{refreshed}"

    rendered_cmd = " ".join(cmd)
    return False, f"Upgrade failed. Run manually: {rendered_cmd}"


def spawn_background_upgrade_check() -> None:
    """Fire-and-forget: run the version check + upgrade in a DETACHED
    subprocess (`python -m claude_statusbar.updater`) so it never blocks a
    status-line render — the upgrade itself can take tens of seconds. The
    detached process re-checks the 24h marker is irrelevant here (the caller
    already gated on it); it just performs the check_and_upgrade once.

    Best-effort: any spawn failure is swallowed so a render is never harmed.
    On a successful upgrade the on-disk package mtime changes, and the daemon's
    code-drift detection (render_thin._is_fresh) restarts it onto new code.
    """
    if is_shadow_install():
        # A duplicate install must not upgrade itself into an entry point
        # another install owns. See is_shadow_install.
        return
    try:
        subprocess.Popen(
            [sys.executable, "-m", "claude_statusbar.updater"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )
    except (OSError, ValueError):
        pass


def check_and_upgrade() -> Tuple[bool, str]:
    """Check for updates and upgrade if available"""
    latest = resolve_latest_version()
    current = get_current_version()

    if not latest:
        return False, "Unable to check for updates"

    _cache_latest_version(latest)

    if not compare_versions(current, latest):
        # Nothing to do is a success. Reporting it as a failure means the
        # detached checker exits 1 on every ordinary day.
        return True, f"Already up to date (v{current})"

    # New version available, try to upgrade
    if auto_upgrade():
        return True, f"Upgraded from v{current} to v{latest}"
    else:
        return (
            False,
            f"Update available (v{latest}) but auto-upgrade failed. "
            f"Run `cs upgrade` to see why.",
        )


if __name__ == "__main__":
    success, message = check_and_upgrade()
    print(message)
    sys.exit(0 if success else 1)
