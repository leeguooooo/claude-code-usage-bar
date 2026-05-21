"""Import-time regression tests.

The status bar is invoked once per second at the user's `refreshInterval`,
so every module pulled in at import time multiplies its cost by 60×/min.
These tests pin which modules MUST stay out of the render-path import
graph. If a future change adds one of them back at module top, the test
fails — pushing the author to either lazy-import it or justify the cost.

Banned imports here are the ones we explicitly deferred in Phase A:
- importlib.metadata: 20ms cumulative (pulls email.message, zipfile, ...)
- subprocess: 8ms cumulative
- shutil: 6ms cumulative

We allow these to be imported by `cs --setup`, `cs doctor`, etc., but not
on the default render path that runs every second.
"""

import subprocess
import sys
from pathlib import Path


REPO_SRC = Path(__file__).resolve().parent.parent / "src"


def _list_imports_for(module: str) -> set[str]:
    """Return all top-level modules pulled in by importing `module`."""
    code = (
        "import sys; "
        f"import {module}; "
        "print('\\n'.join(sorted(sys.modules.keys())))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env={**dict(__import__("os").environ),
             "PYTHONPATH": str(REPO_SRC),
             # Ensure we're not biased by site customizations.
             "PYTHONDONTWRITEBYTECODE": "1"},
        check=True,
    )
    return set(out.stdout.split())


# Modules that MUST NOT appear when importing the cli entry-point. Each of
# these was deferred in Phase A; re-introducing them on the render path
# regresses the per-second startup cost.
BANNED_ON_RENDER_PATH = {
    "importlib.metadata",
    "subprocess",
    "shutil",
}


def test_render_path_does_not_import_banned_modules():
    """Importing claude_statusbar.cli must not pull in heavy stdlib modules.

    Specifically: importlib.metadata, subprocess, shutil. These are deferred
    to the slow paths (claude-monitor subprocess, settings repair, version
    lookup) so the per-render hot path stays cheap.
    """
    loaded = _list_imports_for("claude_statusbar.cli")
    leaked = sorted(BANNED_ON_RENDER_PATH & loaded)
    assert not leaked, (
        f"render-path import regression: {leaked} are loaded just by "
        f"importing claude_statusbar.cli. Move them to lazy local imports "
        f"inside the function(s) that need them."
    )


def test_init_module_does_not_import_metadata():
    """The package __init__ uses PEP 562 lazy attributes for __version__,
    so a bare `import claude_statusbar` must not trigger importlib.metadata."""
    loaded = _list_imports_for("claude_statusbar")
    assert "importlib.metadata" not in loaded, (
        "importlib.metadata loaded just by `import claude_statusbar` — the "
        "lazy __version__ accessor in __init__.py was bypassed."
    )


# ---------------------------------------------------------------------------
# Phase B: render_thin must stay tiny
# ---------------------------------------------------------------------------
RENDER_THIN_BANNED = {
    # Heavy first-party modules that defeat the daemon speedup if pulled in
    # on the fast path.
    "claude_statusbar.core",
    "claude_statusbar.styles",
    "claude_statusbar.themes",
    "claude_statusbar.progress",
    "claude_statusbar.setup",
    "claude_statusbar.daemon",
    # Heavy stdlib already covered above:
    "importlib.metadata",
    "subprocess",
    "shutil",
    "argparse",
}


def test_identity_module_safe_to_import():
    """Importing claude_statusbar.identity must not pull in subprocess.

    The dirty-refresh path lazy-imports subprocess inside the stale
    branch; top-level imports must stay clean so the render hot path
    can call resolve_identity without paying the subprocess cost.
    """
    loaded = _list_imports_for("claude_statusbar.identity")
    assert "subprocess" not in loaded, (
        "identity.py must lazy-import subprocess inside the stale "
        "branch only — found it at top-level import."
    )


def test_render_thin_imports_stay_minimal():
    """`cs render` (Phase B fast path) must import none of the heavy modules.

    If the daemon is alive and rendered.ansi is fresh, the entire render is
    just `read file → write to stdout`. Pulling core/styles/themes into the
    happy path would add ~10ms per tick × 60 ticks/min = pure regression.
    """
    loaded = _list_imports_for("claude_statusbar.render_thin")
    leaked = sorted(RENDER_THIN_BANNED & loaded)
    assert not leaked, (
        f"cs render fast-path import regression: {leaked} are loaded just "
        f"by importing claude_statusbar.render_thin. Move them to lazy "
        f"local imports in the fallback path only."
    )
