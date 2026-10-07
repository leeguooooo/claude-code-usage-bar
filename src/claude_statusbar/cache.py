"""Atomic file write used by every persistent state file (settings.json,
claude-statusbar config, last_stdin cache, etc.).

The old claude-monitor cache.json subsystem (read_cache/write_cache/
refresh_cache_background + cache_refresh.py) was removed — it was orphaned
dead code; the live render path reads official rate_limits from stdin, not a
background-refreshed cache.
"""

import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def file_transaction(path: Path, timeout: float = 0.5):
    """Serialize a complete read/modify/write, with bounded contention."""
    lock_path = path.with_name(path.name + '.lock')
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open('a+b') as handle:
        deadline = time.monotonic() + timeout
        while True:
            try:
                if os.name == 'nt':
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError('cache transaction busy') from None
                time.sleep(0.005)
        try:
            yield
        finally:
            if os.name == 'nt':
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def atomic_write_text(path: Path, text: str, *, durable: bool = True) -> bool:
    """Cross-platform atomic text write. Returns True on success.

    Writes to a sibling tempfile in the same directory, optionally fsyncs, then
    os.replace to swap into place. Same-directory rename is atomic on
    POSIX and on NTFS for replace, so a Ctrl+C / OOM mid-write can
    never leave the destination half-written. Reconstructible render snapshots
    use durable=False; settings and other persistent state keep fsync.
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
                if durable:
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
