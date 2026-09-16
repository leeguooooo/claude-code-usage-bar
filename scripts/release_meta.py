#!/usr/bin/env python3
"""Release metadata for the automated release workflow.

The release workflow needs three facts about a version, and each one is a
place where a hand-run release has gone wrong before: what version we are
releasing, whether every file that carries the version agrees, and what the
release notes say. Doing that in `run:` shell inside the workflow makes it
unreviewable and untestable, so it lives here with tests next to it.

    python scripts/release_meta.py version          # 3.43.2
    python scripts/release_meta.py check 3.43.2     # exits non-zero on drift
    python scripts/release_meta.py title 3.43.2     # v3.43.2 — <headline>
    python scripts/release_meta.py notes 3.43.2     # the CHANGELOG section

`check` is the gate: a release whose plugin.json still says the previous
version ships a marketplace entry that disagrees with the wheel, and nobody
notices until a user reports it.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
CHANGELOG = ROOT / "CHANGELOG.md"
# Every other file that carries the version, and how to read it.
PLUGIN_JSONS = (ROOT / ".claude-plugin" / "plugin.json",
                ROOT / ".claude-plugin" / "marketplace.json")


def pyproject_version(text: str | None = None) -> str:
    text = PYPROJECT.read_text(encoding="utf-8") if text is None else text
    # The first `version = "..."` in [project]; later ones belong to tools.
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not m:
        raise SystemExit("pyproject.toml has no version")
    return m.group(1)


def _plugin_version(data) -> str | None:
    """plugin.json states its version at the top level, marketplace.json under
    `metadata`."""
    if not isinstance(data, dict):
        return None
    for holder in (data, data.get("metadata")):
        if isinstance(holder, dict) and isinstance(holder.get("version"), str):
            return holder["version"]
    return None


def version_drift(version: str, paths=PLUGIN_JSONS) -> list[str]:
    """Files whose version does not match `version`, as human-readable lines."""
    drift = []
    for path in paths:
        if not path.exists():
            continue
        found = _plugin_version(json.loads(path.read_text(encoding="utf-8")))
        if found != version:
            name = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
            drift.append(f"{name}: {found!r} != {version!r}")
    return drift


def changelog_section(version: str, text: str | None = None) -> str:
    """The body of this version's CHANGELOG entry, without its heading.

    Sections run from `## vX.Y.Z` to the next `## v` heading; the `---` rule
    the file puts between entries belongs to neither, so it is trimmed."""
    text = CHANGELOG.read_text(encoding="utf-8") if text is None else text
    pattern = re.compile(
        r"^##\s+v" + re.escape(version) + r"\b[^\n]*\n(.*?)(?=^##\s+v|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    m = pattern.search(text)
    if not m:
        raise SystemExit(f"CHANGELOG.md has no section for v{version}")
    body = m.group(1).strip()
    body = re.sub(r"\n+-{3,}\s*$", "", body).strip()
    if not body:
        raise SystemExit(f"CHANGELOG.md section for v{version} is empty")
    return body


def title(version: str, notes: str | None = None) -> str:
    """`v3.43.2 — <headline>`, taking the headline from the bold one-liner the
    CHANGELOG opens each entry with. Falls back to the bare tag."""
    notes = changelog_section(version) if notes is None else notes
    m = re.search(r"^\*\*(.+?)\*\*\s*$", notes, re.MULTILINE)
    if not m:
        return f"v{version}"
    headline = m.group(1).strip().rstrip(".")
    return f"v{version} — {headline}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=("version", "check", "title", "notes"))
    ap.add_argument("version", nargs="?",
                    help="defaults to the version in pyproject.toml")
    args = ap.parse_args(argv)

    version = args.version or pyproject_version()
    if args.command == "version":
        print(version)
        return 0
    if args.command == "check":
        drift = version_drift(version)
        # The notes must exist before we cut a tag, not after.
        changelog_section(version)
        if drift:
            print("version drift:\n  " + "\n  ".join(drift), file=sys.stderr)
            return 1
        print(f"v{version}: pyproject, plugin manifests and CHANGELOG agree")
        return 0
    if args.command == "title":
        print(title(version))
        return 0
    print(changelog_section(version))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
