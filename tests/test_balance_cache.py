"""Balance cache: fingerprinting, polarity-aware TTL, inflight markers."""
import json
import time

from claude_statusbar.balance_cache import (
    NEGATIVE_TTL_SECONDS,
    TTL_SECONDS,
    cache_path_for,
    clear_inflight,
    fingerprint,
    is_fresh,
    is_inflight,
    mark_inflight,
    read_cache,
    write_cache_atomic,
)


def test_fingerprint_separates_relay_and_key():
    a = fingerprint("https://r1.example", "sk-aaa")
    b = fingerprint("https://r1.example", "sk-bbb")   # same relay, other key
    c = fingerprint("https://r2.example", "sk-aaa")   # other relay, same key
    assert a != b != c and a != c
    # deterministic
    assert a == fingerprint("https://r1.example", "sk-aaa")


def test_fingerprint_never_contains_raw_key():
    fp = fingerprint("https://r.example", "sk-supersecret-token")
    assert "supersecret" not in fp
    assert cache_path_for(fp).suffix == ".json"
    assert cache_path_for(fp).parent.name == "balance"


def test_read_missing_is_none(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert read_cache("deadbeef") is None


def test_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    write_cache_atomic("fp1", {"ts": 100.0, "supported": True, "balance": 12.5})
    got = read_cache("fp1")
    assert got["balance"] == 12.5
    assert got["supported"] is True


def test_corrupt_cache_is_miss(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    p = cache_path_for("fp1")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{nope", encoding="utf-8")
    assert read_cache("fp1") is None


def test_positive_ttl_short_negative_ttl_long():
    now = time.time()
    # supported entry expires after the short TTL
    assert is_fresh({"ts": now, "supported": True}, now) is True
    assert is_fresh({"ts": now - TTL_SECONDS - 1, "supported": True}, now) is False
    # unsupported entry stays fresh far longer (don't re-probe a 404 relay)
    stale_for_positive = now - TTL_SECONDS - 1
    assert is_fresh({"ts": stale_for_positive, "supported": False}, now) is True
    assert is_fresh({"ts": now - NEGATIVE_TTL_SECONDS - 1,
                     "supported": False}, now) is False


def test_is_fresh_guards():
    assert is_fresh(None) is False
    assert is_fresh({}) is False
    assert is_fresh({"ts": "nope", "supported": True}) is False


def test_inflight_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert is_inflight("fp1") is False
    mark_inflight("fp1")
    assert is_inflight("fp1") is True
    clear_inflight("fp1")
    assert is_inflight("fp1") is False


def test_stale_inflight_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    mark_inflight("fp1")
    p = cache_path_for("fp1").with_suffix(".inflight")
    p.write_text(json.dumps({"pid": 1, "ts": time.time() - 120}))
    assert is_inflight("fp1") is False
