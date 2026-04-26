#!/usr/bin/env python3
"""Keep repo-root `commands/` and `src/claude_statusbar/commands/` in sync.

Why two copies?
  - `<repo>/commands/`              — picked up by Claude Code's plugin loader
  - `src/claude_statusbar/commands/` — shipped inside the PyPI wheel for `cs install-commands`

Symlinking the two directories is a Windows / sdist footgun, so we just keep
two real directories and verify they match.

Usage:
    python3 scripts/sync_commands.py            # copy repo-root → package
    python3 scripts/sync_commands.py --check    # exit 1 if they diverge (for CI)
"""

import filecmp
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC  = ROOT / "commands"
DST  = ROOT / "src" / "claude_statusbar" / "commands"


def diff() -> tuple[set[str], set[str], set[str]]:
    """Return (only_in_src, only_in_dst, differing_names)."""
    src_names = {p.name for p in SRC.glob("*.md")}
    dst_names = {p.name for p in DST.glob("*.md")}
    common = src_names & dst_names
    differing = {n for n in common if not filecmp.cmp(SRC / n, DST / n, shallow=False)}
    return src_names - dst_names, dst_names - src_names, differing


def main() -> int:
    check_only = "--check" in sys.argv

    only_src, only_dst, differing = diff()

    if check_only:
        if not (only_src or only_dst or differing):
            print(f"ok: {SRC} and {DST} are in sync ({len(list(SRC.glob('*.md')))} files)")
            return 0
        if only_src:    print(f"missing in package: {sorted(only_src)}")
        if only_dst:    print(f"stale in package:   {sorted(only_dst)}")
        if differing:   print(f"diverged contents:  {sorted(differing)}")
        print("\nrun: python3 scripts/sync_commands.py")
        return 1

    DST.mkdir(parents=True, exist_ok=True)
    for name in sorted({p.name for p in SRC.glob("*.md")} | only_dst):
        if (SRC / name).exists():
            shutil.copy2(SRC / name, DST / name)
            print(f"  + {name}")
        else:
            (DST / name).unlink()
            print(f"  - {name}")
    print(f"synced {SRC} → {DST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
