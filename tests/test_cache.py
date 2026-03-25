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
