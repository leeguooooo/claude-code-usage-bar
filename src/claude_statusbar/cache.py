"""Atomic file write used by every persistent state file (settings.json,
claude-statusbar config, last_stdin cache, etc.).

The old claude-monitor cache.json subsystem (read_cache/write_cache/
refresh_cache_background + cache_refresh.py) was removed — it was orphaned
dead code; the live render path reads official rate_limits from stdin, not a
background-refreshed cache.
"""

import os
import tempfile
from pathlib import Path


def atomic_write_text(path: Path, text: str) -> bool:
    """Cross-platform atomic text write. Returns True on success.

    Writes to a sibling tempfile in the same directory, fsyncs, then
    os.replace to swap into place. Same-directory rename is atomic on
    POSIX and on NTFS for replace, so a Ctrl+C / OOM mid-write can
    never leave the destination half-written.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp",
            dir=str(path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
            return True
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError:
        return False
