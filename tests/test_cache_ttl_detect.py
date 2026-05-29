"""Tests for auto-detecting the prompt-cache TTL from the transcript.

The countdown no longer trusts a fixed config value for the cache TTL.
Instead it reads the ground truth Anthropic reports in every assistant
turn: `message.usage.cache_creation`, which buckets cache-WRITE tokens by
TTL. A nonzero `ephemeral_1h_input_tokens` means that request used a
1-hour `cache_control` ttl; `ephemeral_5m_input_tokens` means 5 minutes.

This is strictly better than any config guess, because the bucket already
reflects subscription vs API-key auth, ENABLE_PROMPT_CACHING_1H,
FORCE_PROMPT_CACHING_5M, and the over-quota -> 5m downgrade.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from claude_statusbar import core


def _write_jsonl(path: Path, entries):
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")


def _install_fake_cache(monkeypatch, tmp_path: Path, payload: dict):
    cache_dir = tmp_path / ".cache" / "claude-statusbar"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "last_stdin.json").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(core.Path, "home", classmethod(lambda cls: tmp_path))


def _assistant(age_s: int, *, ttl_1h: int = 0, ttl_5m: int = 0, with_usage: bool = True):
    """An assistant transcript entry `age_s` seconds old, optionally carrying
    a cache_creation bucket breakdown."""
    ts = (datetime.now(timezone.utc) - timedelta(seconds=age_s)).isoformat()
    entry = {"type": "assistant", "timestamp": ts}
    if with_usage:
        entry["message"] = {"usage": {"cache_creation": {
            "ephemeral_1h_input_tokens": ttl_1h,
            "ephemeral_5m_input_tokens": ttl_5m,
        }}}
    return entry


# ---------------------------------------------------------------------------
# _last_assistant_info — combined (age, detected_ttl) reader
# ---------------------------------------------------------------------------
def test_info_returns_age_and_1h_ttl(tmp_path: Path):
    t = tmp_path / "t.jsonl"
    _write_jsonl(t, [_assistant(120, ttl_1h=1000)])
    info = core._last_assistant_info(str(t))
    assert info is not None
    age, ttl = info
    assert 115 <= age <= 150
    assert ttl == 3600


def test_info_returns_5m_ttl(tmp_path: Path):
    t = tmp_path / "t.jsonl"
    _write_jsonl(t, [_assistant(30, ttl_5m=1000)])
    age, ttl = core._last_assistant_info(str(t))
    assert ttl == 300


def test_info_ttl_none_when_no_usage(tmp_path: Path):
    t = tmp_path / "t.jsonl"
    _write_jsonl(t, [_assistant(30, with_usage=False)])
    age, ttl = core._last_assistant_info(str(t))
    assert age is not None
    assert ttl is None


def test_info_none_when_no_assistant(tmp_path: Path):
    t = tmp_path / "t.jsonl"
    _write_jsonl(t, [{"type": "user", "timestamp": datetime.now(timezone.utc).isoformat()}])
    assert core._last_assistant_info(str(t)) is None


def test_age_decoupled_from_ttl_when_last_turn_wrote_nothing(tmp_path: Path):
    """Age comes from the NEWEST assistant entry; TTL from the newest entry
    that actually WROTE cache. A final turn that wrote nothing (both buckets
    0) must not erase the detected TTL — fall through to the older write."""
    t = tmp_path / "t.jsonl"
    _write_jsonl(t, [
        _assistant(200, ttl_1h=5000),   # older: established the 1h cache
        _assistant(100, ttl_1h=0, ttl_5m=0),  # newest: read-only turn, no write
    ])
    age, ttl = core._last_assistant_info(str(t))
    assert 95 <= age <= 130          # age from the newest (100s) entry
    assert ttl == 3600               # ttl from the older write


# ---------------------------------------------------------------------------
# get_cache_age_text — auto-detect end to end (no ttl arg)
# ---------------------------------------------------------------------------
def test_autodetects_1h(tmp_path: Path, monkeypatch):
    """600s into a 1h cache => ~50m remaining, NOT COLD (which a 300s default
    would wrongly show)."""
    t = tmp_path / "t.jsonl"
    _write_jsonl(t, [_assistant(600, ttl_1h=1000)])
    _install_fake_cache(monkeypatch, tmp_path, {"transcript_path": str(t)})
    out = core.get_cache_age_text()
    assert out.startswith(("50m", "49m")) and out.endswith("s"), \
        f"expected ~50m..s auto-detected, got {out!r}"


def test_autodetects_5m(tmp_path: Path, monkeypatch):
    """360s into a 5m cache => expired => COLD."""
    t = tmp_path / "t.jsonl"
    _write_jsonl(t, [_assistant(360, ttl_5m=1000)])
    _install_fake_cache(monkeypatch, tmp_path, {"transcript_path": str(t)})
    assert core.get_cache_age_text() == "COLD"


def test_autodetect_uses_older_write_ttl(tmp_path: Path, monkeypatch):
    t = tmp_path / "t.jsonl"
    _write_jsonl(t, [
        _assistant(200, ttl_1h=5000),
        _assistant(100, ttl_1h=0, ttl_5m=0),
    ])
    _install_fake_cache(monkeypatch, tmp_path, {"transcript_path": str(t)})
    out = core.get_cache_age_text()
    # 3600 - 100 = 3500s = 58m20s -> "MMmSSs"
    assert out.startswith(("58m", "57m", "59m")) and out.endswith("s"), \
        f"expected ~58m..s, got {out!r}"


def test_falls_back_to_300_when_no_write_signal(tmp_path: Path, monkeypatch):
    """No cache_creation anywhere (ancient transcript / caching disabled):
    fall back to the conservative 300s, NOT 3600. 100s elapsed => ~3m left."""
    t = tmp_path / "t.jsonl"
    _write_jsonl(t, [_assistant(100, with_usage=False)])
    _install_fake_cache(monkeypatch, tmp_path, {"transcript_path": str(t)})
    out = core.get_cache_age_text()
    assert out.startswith("3m"), f"fallback must be 300s (=> 3m..), got {out!r}"


def test_explicit_ttl_override_still_supported(tmp_path: Path, monkeypatch):
    """Passing an explicit ttl bypasses detection (test/override seam)."""
    t = tmp_path / "t.jsonl"
    _write_jsonl(t, [_assistant(600, ttl_1h=1000)])  # would auto-detect 1h
    _install_fake_cache(monkeypatch, tmp_path, {"transcript_path": str(t)})
    # Force 300 explicitly -> 600s elapsed -> COLD, ignoring the 1h signal.
    assert core.get_cache_age_text(300) == "COLD"
