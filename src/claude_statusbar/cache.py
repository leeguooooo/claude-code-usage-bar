"""Cache layer for claude-monitor data.

Atomic writes, age-based invalidation, and stale-read support for
serving old data while a background refresh runs.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional

CACHE_MAX_AGE_S = 30
CACHE_DIR = Path.home() / ".cache" / "claude-statusbar"
CACHE_FILE = CACHE_DIR / "cache.json"


def read_cache(path: Path = CACHE_FILE) -> Optional[Dict[str, Any]]:
    """Read cache if fresh (<CACHE_MAX_AGE_S seconds old).

    Returns None if missing, corrupt, or stale.
    """
    try:
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        cache_time = raw.get("_cache_time", 0)
        if time.time() - cache_time > CACHE_MAX_AGE_S:
            return None
        return raw
    except (json.JSONDecodeError, OSError):
        return None


def read_cache_stale(path: Path = CACHE_FILE) -> Optional[Dict[str, Any]]:
    """Read cache regardless of age. Returns None only if missing/corrupt."""
    try:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def write_cache(data: Dict[str, Any], path: Path = CACHE_FILE) -> None:
    """Atomically write data to cache file.

    Writes to a temp file first, then renames to prevent partial reads.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {**data, "_cache_time": time.time()}
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.rename(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def refresh_cache_background() -> None:
    """Spawn a detached subprocess to refresh the cache.

    The subprocess runs `python -m claude_statusbar.cache_refresh` which
    calls claude-monitor and writes the result to cache. This way the
    main process can return immediately with stale data.
    """
    try:
        subprocess.Popen(
            [sys.executable, "-m", "claude_statusbar.cache_refresh"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        pass
