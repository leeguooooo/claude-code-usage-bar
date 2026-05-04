"""Tests for the cache-age widget (get_cache_age_text + _last_assistant_age)."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from claude_statusbar import core


def _write_jsonl(path: Path, entries):
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")


def _install_fake_cache(monkeypatch, tmp_path: Path, payload: dict):
    """Point Path.home() at tmp_path so get_cache_age_text() reads our cache."""
    cache_dir = tmp_path / ".cache" / "claude-statusbar"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "last_stdin.json").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(core.Path, "home", classmethod(lambda cls: tmp_path))


# ---------------------------------------------------------------------------
# _last_assistant_age
# ---------------------------------------------------------------------------
def test_finds_most_recent_assistant(tmp_path: Path):
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


def test_returns_none_when_no_assistant(tmp_path: Path):
    transcript = tmp_path / "t.jsonl"
    _write_jsonl(transcript, [{"type": "user", "timestamp": datetime.now(timezone.utc).isoformat()}])
    assert core._last_assistant_age(str(transcript)) is None


def test_handles_z_suffix_timestamp(tmp_path: Path):
    transcript = tmp_path / "t.jsonl"
    ts = (datetime.now(timezone.utc) - timedelta(seconds=10)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    _write_jsonl(transcript, [{"type": "assistant", "timestamp": ts}])
    age = core._last_assistant_age(str(transcript))
    assert age is not None
    assert 0 <= age <= 30


def test_handles_naive_timestamp_without_crashing(tmp_path: Path):
    """A naive ISO timestamp (no Z, no offset) used to crash with TypeError
    on aware-minus-naive subtraction. We treat it as UTC."""
    transcript = tmp_path / "t.jsonl"
    ts = (datetime.now(timezone.utc) - timedelta(seconds=10)).strftime("%Y-%m-%dT%H:%M:%S.000")
    _write_jsonl(transcript, [{"type": "assistant", "timestamp": ts}])
    age = core._last_assistant_age(str(transcript))
    assert age is not None
    assert 0 <= age <= 30


def test_skips_malformed_lines(tmp_path: Path):
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


def test_empty_file_returns_none(tmp_path: Path):
    transcript = tmp_path / "empty.jsonl"
    transcript.write_bytes(b"")
    assert core._last_assistant_age(str(transcript)) is None


def test_missing_file_returns_none(tmp_path: Path):
    assert core._last_assistant_age(str(tmp_path / "nope.jsonl")) is None


def test_no_trailing_newline(tmp_path: Path):
    transcript = tmp_path / "t.jsonl"
    ts = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
    transcript.write_text(json.dumps({"type": "assistant", "timestamp": ts}), encoding="utf-8")
    age = core._last_assistant_age(str(transcript))
    assert age is not None
    assert 0 <= age <= 30


def test_trailing_blank_lines_are_skipped(tmp_path: Path):
    transcript = tmp_path / "t.jsonl"
    ts = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
    transcript.write_text(
        json.dumps({"type": "assistant", "timestamp": ts}) + "\n\n\n\n",
        encoding="utf-8",
    )
    age = core._last_assistant_age(str(transcript))
    assert age is not None
    assert 0 <= age <= 30


def test_assistant_line_straddles_chunk_boundary(tmp_path: Path):
    """Place the assistant JSON line so that bytes around `file_size - 32KB`
    fall in the middle of it. The first reverse-read chunk gets only the
    line's tail; the second chunk must stitch it back together."""
    transcript = tmp_path / "t.jsonl"
    ts = (datetime.now(timezone.utc) - timedelta(seconds=20)).isoformat()
    assistant_line = json.dumps({"type": "assistant", "timestamp": ts}) + "\n"

    # Pad before so the assistant line crosses the (file_size - 32KB) boundary.
    # boundary = file_size - chunk = prefix_len + line_len + suffix_len - chunk
    # For boundary to fall *inside* [line_start, line_end] we need
    #   suffix_len in (chunk - line_len, chunk).
    # Choose suffix_len = chunk - line_len // 2 so the boundary lands mid-line.
    chunk = core._CACHE_AGE_CHUNK
    prefix = b"x" * 99 + b"\n"  # short noise prefix, will fail JSON parse
    line_bytes = assistant_line.encode()
    suffix_len = chunk - len(line_bytes) // 2
    suffix = (b"x" * 199 + b"\n") * (suffix_len // 200) + b"x" * (suffix_len % 200)
    transcript.write_bytes(prefix + line_bytes + suffix)

    file_size = transcript.stat().st_size
    boundary = file_size - chunk
    line_start = len(prefix)
    line_end = line_start + len(assistant_line)
    # Sanity: assistant line truly straddles the chunk boundary.
    assert line_start < boundary < line_end, (
        f"test setup wrong: line=[{line_start},{line_end}) boundary={boundary}"
    )

    age = core._last_assistant_age(str(transcript))
    assert age is not None
    assert 0 <= age <= 60


def test_byte_cap_stops_before_reading_entire_huge_file(tmp_path: Path):
    """Place the only assistant entry at byte 0, then pad with > _MAX_BYTES of
    junk. The reverse-tail reader must give up at the cap rather than scanning
    the whole file on every render."""
    transcript = tmp_path / "huge.jsonl"
    ts = datetime.now(timezone.utc).isoformat()
    head = json.dumps({"type": "assistant", "timestamp": ts}) + "\n"
    # Pad past the cap so the assistant entry is unreachable within the budget.
    pad_size = core._CACHE_AGE_MAX_BYTES + 50 * 1024
    pad = (b"x" * 200 + b"\n") * (pad_size // 201 + 1)
    transcript.write_bytes(head.encode() + pad)
    assert transcript.stat().st_size > core._CACHE_AGE_MAX_BYTES

    assert core._last_assistant_age(str(transcript)) is None


# ---------------------------------------------------------------------------
# get_cache_age_text
# ---------------------------------------------------------------------------
def test_cache_text_cold_when_assistant_is_old(tmp_path: Path, monkeypatch):
    transcript = tmp_path / "t.jsonl"
    old = datetime.now(timezone.utc) - timedelta(seconds=400)
    _write_jsonl(transcript, [{"type": "assistant", "timestamp": old.isoformat()}])
    _install_fake_cache(monkeypatch, tmp_path, {"transcript_path": str(transcript)})
    assert core.get_cache_age_text() == "COLD"


def test_cache_text_cold_when_no_assistant_yet(tmp_path: Path, monkeypatch):
    """Used to fall back to last_stdin.json mtime and report '0s ago' for a
    fresh cache, even though semantically the prompt cache is cold."""
    transcript = tmp_path / "t.jsonl"
    _write_jsonl(transcript, [
        {"type": "user", "timestamp": datetime.now(timezone.utc).isoformat()},
    ])
    _install_fake_cache(monkeypatch, tmp_path, {"transcript_path": str(transcript)})
    assert core.get_cache_age_text() == "COLD"


def test_cache_text_warm_minutes_format(tmp_path: Path, monkeypatch):
    transcript = tmp_path / "t.jsonl"
    ts = datetime.now(timezone.utc) - timedelta(seconds=130)
    _write_jsonl(transcript, [{"type": "assistant", "timestamp": ts.isoformat()}])
    _install_fake_cache(monkeypatch, tmp_path, {"transcript_path": str(transcript)})
    out = core.get_cache_age_text()
    assert out.startswith("2m")
    assert out.endswith("s")


def test_cache_text_empty_when_cache_missing(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(core.Path, "home", classmethod(lambda cls: tmp_path))
    assert core.get_cache_age_text() == ""


def test_cache_text_empty_when_no_transcript_path(tmp_path: Path, monkeypatch):
    """No transcript_path field → no signal at all; segment hidden."""
    _install_fake_cache(monkeypatch, tmp_path, {"some_other_field": "x"})
    assert core.get_cache_age_text() == ""


def test_cache_text_respects_custom_ttl(tmp_path: Path, monkeypatch):
    """Users on the 1h Anthropic cache pass ttl_seconds=3600; entries between
    300s and 3600s should still report warm, not COLD."""
    transcript = tmp_path / "t.jsonl"
    ts = datetime.now(timezone.utc) - timedelta(seconds=600)  # 10 min old
    _write_jsonl(transcript, [{"type": "assistant", "timestamp": ts.isoformat()}])
    _install_fake_cache(monkeypatch, tmp_path, {"transcript_path": str(transcript)})
    # Default 300s TTL → COLD
    assert core.get_cache_age_text(300) == "COLD"
    # 1h TTL → still warm, formatted as 10m
    out = core.get_cache_age_text(3600)
    assert out.startswith("10m"), f"expected 10m..., got {out!r}"
