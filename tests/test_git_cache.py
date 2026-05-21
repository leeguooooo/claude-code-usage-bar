"""Git dirty-cache read/write + inflight-marker."""
import json
import time

from claude_statusbar.git_cache import (
    TTL_SECONDS,
    cache_path_for,
    clear_inflight,
    is_fresh,
    is_inflight,
    mark_inflight,
    read_cache,
    write_cache_atomic,
)


def test_cache_path_deterministic(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    a = cache_path_for("/srv/proj")
    b = cache_path_for("/srv/proj")
    assert a == b
    assert a.suffix == ".json"
    assert a.parent.name == "git"


def test_read_returns_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert read_cache("/no/such/repo") is None


def test_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    write_cache_atomic("/srv/proj", {"branch": "main", "dirty": False, "ts": 100.0})
    got = read_cache("/srv/proj")
    assert got["branch"] == "main"
    assert got["dirty"] is False


def test_corrupt_cache_treated_as_miss(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    p = cache_path_for("/srv/proj")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json", encoding="utf-8")
    assert read_cache("/srv/proj") is None


def test_inflight_marker_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert is_inflight("/srv/proj") is False
    mark_inflight("/srv/proj")
    assert is_inflight("/srv/proj") is True
    clear_inflight("/srv/proj")
    assert is_inflight("/srv/proj") is False


def test_stale_inflight_marker_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    mark_inflight("/srv/proj")
    p = cache_path_for("/srv/proj").with_suffix(".inflight")
    old = time.time() - 60
    p.write_text(json.dumps({"pid": 1, "ts": old}))
    assert is_inflight("/srv/proj") is False


def test_ttl_constant_is_five_seconds():
    assert TTL_SECONDS == 5


def test_is_fresh_within_ttl():
    assert is_fresh({"ts": time.time()}) is True
    assert is_fresh({"ts": time.time() - 10}) is False
    assert is_fresh(None) is False
    assert is_fresh({}) is False
