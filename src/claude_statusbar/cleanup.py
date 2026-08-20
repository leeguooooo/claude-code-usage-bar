"""Remove orphaned runtime directories left by legacy onefile builds.

Versions through 3.32.3 shipped the macOS binary as a PyInstaller onefile.
Claude Code invokes ``cs render`` once per second; when it killed a render while
PyInstaller was still extracting PyObjC, the bootloader never removed its
``_MEI*`` directory. The onedir installer invokes this module once after it has
stopped the old daemon and switched the status-line command to the new bundle.

The cleanup is intentionally conservative:

* macOS only (the affected bundle is the PyObjC build);
* current user's real directories directly below the user temp directory;
* at least ten minutes old;
* the distinctive Python + PyObjC prefix extracted by the legacy ``cs`` bundle;
* no open file below the directory, according to macOS ``lsof``; and
* at least three matching siblings, so a lone unrelated PyInstaller directory
  is never claimed as a ``cs`` leak.

If the open-file inventory cannot be obtained, nothing is deleted.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


_MEI_NAME = re.compile(r"_MEI[A-Za-z0-9]{6,}$")
_LEGACY_CS_PREFIX = frozenset(
    {"AppKit", "CoreFoundation", "Foundation", "Python.framework"}
)
DEFAULT_MIN_AGE_S = 10 * 60
DEFAULT_MIN_COHORT = 3
_LSOF_TIMEOUT_S = 20


@dataclass(frozen=True)
class CleanupResult:
    scanned: int = 0
    matched: int = 0
    removed: int = 0
    skipped_active: int = 0
    bytes_freed: int = 0
    reason: str = ""


def _looks_like_legacy_cs_mei(path: Path) -> bool:
    """Recognize both partial and complete extractions of the old mac bundle."""
    try:
        names = {entry.name for entry in path.iterdir()}
    except OSError:
        return False
    return _LEGACY_CS_PREFIX.issubset(names)


def _active_mei_dirs(temp_root: Path) -> Optional[set[Path]]:
    """Return ``_MEI`` roots containing an open file, or ``None`` on failure.

    One global ``lsof`` snapshot is much cheaper than launching ``lsof +D`` for
    thousands of candidates. Only path records are retained; command names and
    other open files are ignored and never logged.
    """
    try:
        proc = subprocess.run(
            ["/usr/sbin/lsof", "-nP", "-Fn"],
            capture_output=True,
            text=True,
            timeout=_LSOF_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None

    root = temp_root.resolve()
    active: set[Path] = set()
    for line in proc.stdout.splitlines():
        if not line.startswith("n/"):
            continue
        raw = line[1:]
        try:
            rel = Path(raw).relative_to(root)
        except (ValueError, OSError):
            continue
        if not rel.parts or not _MEI_NAME.fullmatch(rel.parts[0]):
            continue
        active.add(root / rel.parts[0])
    return active


def _tree_size(path: Path) -> int:
    total = 0
    for base, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(base) / name).stat().st_size
            except OSError:
                pass
    return total


def cleanup_legacy_mei_dirs(
    *,
    temp_root: Optional[Path] = None,
    now: Optional[float] = None,
    min_age_s: float = DEFAULT_MIN_AGE_S,
    min_cohort: int = DEFAULT_MIN_COHORT,
    active_dirs: Optional[set[Path]] = None,
    platform: Optional[str] = None,
) -> CleanupResult:
    """Delete inactive legacy ``cs`` extraction directories.

    ``active_dirs`` is injectable for tests. In production, omitting it takes a
    global open-file snapshot. A failed snapshot aborts cleanup rather than
    guessing whether an old directory is still backing a long-running process.
    """
    if (platform or sys.platform) != "darwin":
        return CleanupResult(reason="not macOS")

    root = Path(temp_root or tempfile.gettempdir())
    try:
        root = root.resolve(strict=True)
        children = list(root.iterdir())
    except OSError as exc:
        return CleanupResult(reason=f"temp directory unavailable: {exc}")

    if active_dirs is None:
        active_dirs = _active_mei_dirs(root)
        if active_dirs is None:
            return CleanupResult(reason="could not verify open files")
    else:
        active_dirs = {Path(p).resolve() for p in active_dirs}

    timestamp = time.time() if now is None else now
    uid = os.getuid()
    scanned = 0
    candidates: list[Path] = []
    skipped_active = 0

    for path in children:
        if not _MEI_NAME.fullmatch(path.name) or path.is_symlink():
            continue
        scanned += 1
        try:
            st = path.stat()
        except OSError:
            continue
        if not path.is_dir() or st.st_uid != uid:
            continue
        if timestamp - st.st_mtime < min_age_s:
            continue
        if not _looks_like_legacy_cs_mei(path):
            continue
        if path.resolve() in active_dirs:
            skipped_active += 1
            continue
        candidates.append(path)

    matched = len(candidates)
    if matched < max(1, min_cohort):
        return CleanupResult(
            scanned=scanned,
            matched=matched,
            skipped_active=skipped_active,
            reason="no legacy cs leak cohort",
        )

    removed = 0
    bytes_freed = 0
    for path in candidates:
        size = _tree_size(path)
        try:
            shutil.rmtree(path)
        except OSError:
            continue
        removed += 1
        bytes_freed += size

    return CleanupResult(
        scanned=scanned,
        matched=matched,
        removed=removed,
        skipped_active=skipped_active,
        bytes_freed=bytes_freed,
    )


def _human_bytes(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024 or unit == "TB":
            return f"{amount:.1f} {unit}" if unit != "B" else f"{int(amount)} B"
        amount /= 1024
    return f"{value} B"


def main() -> int:
    result = cleanup_legacy_mei_dirs()
    if result.removed:
        noun = "directory" if result.removed == 1 else "directories"
        print(
            f"Recovered {_human_bytes(result.bytes_freed)} from "
            f"{result.removed} stale cs runtime {noun}."
        )
    elif result.reason and result.reason not in ("not macOS", "no legacy cs leak cohort"):
        print(f"Skipped legacy runtime cleanup: {result.reason}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
