"""Release guard: the version must be bumped in ALL THREE places at once.

`pyproject.toml` is the PyPI source of truth, but the Claude plugin marketplace
reads its own `.claude-plugin/marketplace.json` + `plugin.json`. Those were
silently left at 3.10.0 while the CLI went 3.11.0 → 3.12.0 because releases only
bumped pyproject. This test fails the moment they drift, so the mistake is caught
before a release instead of by a user noticing a stale marketplace version.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _pyproject_version() -> str:
    txt = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', txt, re.MULTILINE)
    assert m, "version not found in pyproject.toml"
    return m.group(1)


def test_marketplace_and_plugin_versions_match_pyproject():
    v = _pyproject_version()
    mkt = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text("utf-8"))
    plg = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text("utf-8"))
    assert mkt["metadata"]["version"] == v, (
        f"marketplace.json metadata.version={mkt['metadata']['version']!r} "
        f"!= pyproject {v!r} — bump .claude-plugin/marketplace.json on release"
    )
    assert plg["version"] == v, (
        f"plugin.json version={plg['version']!r} != pyproject {v!r} "
        f"— bump .claude-plugin/plugin.json on release"
    )
