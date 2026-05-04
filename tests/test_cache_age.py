"""Tests for the cache-age widget (get_cache_age_text + _last_assistant_age)."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from claude_statusbar import core


def _write_jsonl(path: Path, entries):
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")


def _stub_cache(monkeypatch, tmp_path: Path, transcript_path: str):
    cache = tmp_path / "last_stdin.json"
    cache.write_text(json.dumps({"transcript_path": transcript_path}), encoding="utf-8")

    class _FakeHome:
        def __truediv__(self, _other):
            class _Joiner:
                def __init__(self, base):
                    self._p = base

                def __truediv__(self, more):
                    self._p = self._p / more
                    return self

                def read_text(self, **kw):
                    return self._p.read_text(**kw)

                def stat(self):
                    return self._p.stat()

            return _Joiner(tmp_path)

    monkeypatch.setattr(core.Path, "home", classmethod(lambda cls: _FakeHome()))
    return cache


def test_last_assistant_age_finds_most_recent(tmp_path: Path):
    transcript = tmp_path / "t.jsonl"
    now = datetime.now(timezone.utc)
    _write_jsonl(transcript, [
        {"type": "user", "timestamp": (now - timedelta(seconds=600)).isoformat()},
        {"type": "assistant", "timestamp": (now - timedelta(seconds=300)).isoformat()},
        {"type": "user", "timestamp": (now - timedelta(seconds=120)).isoformat()},
        {"type": "assistant", "timestamp": (now - timedelta(seconds=30)).isoformat()},
    ])
    age = core._last_assistant_age(str(transcript))
    assert age is not None
    assert 25 <= age <= 60


def test_last_assistant_age_returns_none_when_no_assistant(tmp_path: Path):
    transcript = tmp_path / "t.jsonl"
    now = datetime.now(timezone.utc)
    _write_jsonl(transcript, [
        {"type": "user", "timestamp": now.isoformat()},
    ])
    assert core._last_assistant_age(str(transcript)) is None


def test_last_assistant_age_handles_z_suffix(tmp_path: Path):
    transcript = tmp_path / "t.jsonl"
    now = datetime.now(timezone.utc)
    ts = (now - timedelta(seconds=10)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    _write_jsonl(transcript, [{"type": "assistant", "timestamp": ts}])
    age = core._last_assistant_age(str(transcript))
    assert age is not None
    assert 0 <= age <= 30


def test_last_assistant_age_skips_malformed_lines(tmp_path: Path):
    transcript = tmp_path / "t.jsonl"
    now = datetime.now(timezone.utc)
    transcript.write_text(
        "not-json\n"
        + json.dumps({"type": "assistant", "timestamp": (now - timedelta(seconds=5)).isoformat()})
        + "\n"
        + "also-not-json\n",
        encoding="utf-8",
    )
    age = core._last_assistant_age(str(transcript))
    assert age is not None
    assert 0 <= age <= 30


def test_last_assistant_age_works_across_chunk_boundary(tmp_path: Path, monkeypatch):
    """The reverse-tail reader splits the file into chunks; assistant entries
    should still be findable when split across two reads."""
    monkeypatch.setattr(core, "_last_assistant_age", core._last_assistant_age)
    transcript = tmp_path / "t.jsonl"
    now = datetime.now(timezone.utc)
    # Pad with bulky user entries so the assistant entry is past the first
    # 32KB chunk boundary (counting from the end).
    padding = [
        {"type": "user", "text": "x" * 2000, "timestamp": now.isoformat()}
        for _ in range(40)
    ]
    entries = [
        {"type": "assistant", "timestamp": (now - timedelta(seconds=15)).isoformat()},
    ] + padding
    _write_jsonl(transcript, entries)
    age = core._last_assistant_age(str(transcript))
    assert age is not None
    assert 0 <= age <= 60


def test_last_assistant_age_returns_none_on_missing_file(tmp_path: Path):
    assert core._last_assistant_age(str(tmp_path / "nope.jsonl")) is None


def test_get_cache_age_text_cold(tmp_path: Path, monkeypatch):
    transcript = tmp_path / "t.jsonl"
    old = datetime.now(timezone.utc) - timedelta(seconds=400)
    _write_jsonl(transcript, [{"type": "assistant", "timestamp": old.isoformat()}])
    monkeypatch.setattr(core.Path, "home", classmethod(lambda cls: tmp_path.parent))
    cache_dir = tmp_path.parent / ".cache" / "claude-statusbar"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "last_stdin.json").write_text(
        json.dumps({"transcript_path": str(transcript)}), encoding="utf-8"
    )
    assert core.get_cache_age_text() == "COLD"


def test_get_cache_age_text_warm_minutes(tmp_path: Path, monkeypatch):
    transcript = tmp_path / "t.jsonl"
    ts = datetime.now(timezone.utc) - timedelta(seconds=130)
    _write_jsonl(transcript, [{"type": "assistant", "timestamp": ts.isoformat()}])
    monkeypatch.setattr(core.Path, "home", classmethod(lambda cls: tmp_path.parent))
    cache_dir = tmp_path.parent / ".cache" / "claude-statusbar"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "last_stdin.json").write_text(
        json.dumps({"transcript_path": str(transcript)}), encoding="utf-8"
    )
    out = core.get_cache_age_text()
    assert out.endswith(" ago")
    assert out.startswith("2m")


def test_get_cache_age_text_returns_empty_when_no_cache(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(core.Path, "home", classmethod(lambda cls: tmp_path))
    assert core.get_cache_age_text() == ""
