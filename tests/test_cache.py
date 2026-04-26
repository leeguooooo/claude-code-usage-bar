# tests/test_cache.py
import json
import time
from pathlib import Path
from claude_statusbar.cache import (
    read_cache, read_cache_stale, write_cache, CACHE_MAX_AGE_S,
)

def test_write_and_read(tmp_path):
    cache_file = tmp_path / "cache.json"
    data = {"messages_count": 100, "message_limit": 250}
    write_cache(data, cache_file)
    result = read_cache(cache_file)
    assert result is not None
    assert result["messages_count"] == 100

def test_read_missing_file(tmp_path):
    cache_file = tmp_path / "nonexistent.json"
    assert read_cache(cache_file) is None

def test_read_stale_cache_returns_none(tmp_path):
    cache_file = tmp_path / "cache.json"
    data = {"messages_count": 50}
    write_cache(data, cache_file)
    raw = json.loads(cache_file.read_text())
    raw["_cache_time"] = time.time() - CACHE_MAX_AGE_S - 10
    cache_file.write_text(json.dumps(raw))
    assert read_cache(cache_file) is None

def test_read_stale_cache_with_stale_ok(tmp_path):
    """read_cache_stale returns data even if expired."""
    cache_file = tmp_path / "cache.json"
    write_cache({"messages_count": 50}, cache_file)
    raw = json.loads(cache_file.read_text())
    raw["_cache_time"] = time.time() - CACHE_MAX_AGE_S - 10
    cache_file.write_text(json.dumps(raw))
    result = read_cache_stale(cache_file)
    assert result is not None
    assert result["messages_count"] == 50

def test_write_is_atomic(tmp_path):
    """Cache file should never be half-written."""
    cache_file = tmp_path / "cache.json"
    write_cache({"a": 1}, cache_file)
    result = json.loads(cache_file.read_text())
    assert "_cache_time" in result


def test_write_overwrites_existing_file(tmp_path):
    """os.replace must succeed even when the target already exists.
    Regression test for the os.rename → os.replace migration that fixed
    a Windows-only FileExistsError."""
    cache_file = tmp_path / "cache.json"
    write_cache({"a": 1}, cache_file)
    write_cache({"a": 2}, cache_file)  # second write must not raise
    result = read_cache(cache_file)
    assert result is not None
    assert result["a"] == 2


def test_write_leaves_no_temp_file(tmp_path):
    cache_file = tmp_path / "cache.json"
    write_cache({"x": 1}, cache_file)
    leftover = list(tmp_path.glob("*.tmp"))
    assert leftover == [], f"temp files leaked: {leftover}"


# ---------------------------------------------------------------------------
# atomic_write_text — used by every persistent state file in the package.
# ---------------------------------------------------------------------------
import os
from claude_statusbar.cache import atomic_write_text


def test_atomic_write_text_creates_file(tmp_path):
    p = tmp_path / "sub" / "file.txt"
    assert atomic_write_text(p, "hello") is True
    assert p.read_text(encoding="utf-8") == "hello"


def test_atomic_write_text_overwrites(tmp_path):
    p = tmp_path / "f.txt"
    atomic_write_text(p, "v1")
    atomic_write_text(p, "v2")
    assert p.read_text(encoding="utf-8") == "v2"


def test_atomic_write_text_no_temp_on_failure(tmp_path, monkeypatch):
    """If os.replace fails, the temp file must be cleaned up."""
    p = tmp_path / "f.txt"
    real_replace = os.replace

    def fail(*args, **kwargs):
        raise OSError("simulated")

    monkeypatch.setattr(os, "replace", fail)
    # write may or may not raise depending on inner handling — what matters
    # is no leftover .tmp file.
    try:
        atomic_write_text(p, "data")
    except OSError:
        pass
    leftover = list(tmp_path.glob(".f.txt.*.tmp"))
    assert leftover == [], f"temp files leaked: {leftover}"


def test_atomic_write_text_no_temp_on_success(tmp_path):
    p = tmp_path / "f.txt"
    atomic_write_text(p, "data")
    leftover = list(tmp_path.glob(".f.txt.*.tmp"))
    assert leftover == []


def test_atomic_write_text_returns_false_on_readonly_dir(tmp_path):
    """If the parent dir is read-only, atomic_write_text returns False rather
    than raising. Callers (statusLine render path) depend on this contract."""
    ro = tmp_path / "ro"
    ro.mkdir()
    os.chmod(ro, 0o444)
    try:
        # mkdir on a child path of read-only dir should fail with OSError
        result = atomic_write_text(ro / "nested" / "file.txt", "data")
        assert result is False
    finally:
        os.chmod(ro, 0o755)  # so pytest can clean up
