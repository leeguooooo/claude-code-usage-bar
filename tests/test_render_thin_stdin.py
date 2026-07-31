"""`cs render` must not outlive the payload it was handed.

`sys.stdin.buffer.read()` returns at EOF, and EOF needs *every* write handle
on the pipe to close — not just the shell Claude Code spawned the statusLine
through. On Windows a sibling process that inherited the handle keeps the pipe
open after that shell exits, so the render process blocks forever with the
complete payload already in memory.
"""

import json
import sys

import pytest

from claude_statusbar import render_thin


PAYLOAD = json.dumps({
    "session_id": "abc-123",
    "model": {"id": "claude-opus-5", "display_name": "Opus 5"},
    "context_window": {"context_window_size": 1_000_000,
                       "used_percentage": 6,
                       "total_input_tokens": 63_824},
}).encode("utf-8")


class _FakeBuffer:
    """Hands out `chunks`, then blocks — standing in for a pipe that never
    reaches EOF because someone else still holds the write end."""

    def __init__(self, chunks):
        self._chunks = list(chunks)
        self.reads = 0

    def read1(self, _size):
        self.reads += 1
        if self._chunks:
            return self._chunks.pop(0)
        raise AssertionError("read1 called after the payload was complete "
                             "— this is the call that hangs in production")

    def read(self, *_a):  # pragma: no cover - guard, must never be reached
        raise AssertionError("read() would block until EOF")


class _FakeStdin:
    def __init__(self, chunks, tty=False):
        self.buffer = _FakeBuffer(chunks)
        self._tty = tty

    def isatty(self):
        return self._tty


def test_stops_at_end_of_json_without_waiting_for_eof(monkeypatch):
    stdin = _FakeStdin([PAYLOAD])
    monkeypatch.setattr(sys, "stdin", stdin)

    assert render_thin._consume_stdin() == PAYLOAD
    assert stdin.buffer.reads == 1


def test_reassembles_a_payload_split_across_chunks(monkeypatch):
    half = len(PAYLOAD) // 2
    stdin = _FakeStdin([PAYLOAD[:half], PAYLOAD[half:]])
    monkeypatch.setattr(sys, "stdin", stdin)

    assert render_thin._consume_stdin() == PAYLOAD
    assert stdin.buffer.reads == 2


def test_non_json_input_still_reads_to_eof(monkeypatch):
    """No JSON document to bound on — fall back to the old EOF behaviour
    rather than truncating whatever the caller sent."""
    stdin = _FakeStdin([b"not json", b""])
    monkeypatch.setattr(sys, "stdin", stdin)

    assert render_thin._consume_stdin() == b"not json"


def test_interactive_stdin_returns_none(monkeypatch):
    monkeypatch.setattr(sys, "stdin", _FakeStdin([PAYLOAD], tty=True))

    assert render_thin._consume_stdin() is None


def test_empty_stdin_returns_none(monkeypatch):
    monkeypatch.setattr(sys, "stdin", _FakeStdin([b""]))

    assert render_thin._consume_stdin() is None


def test_session_id_survives_the_bounded_read(monkeypatch):
    """The bytes handed back must still route to the right session bucket."""
    monkeypatch.setattr(sys, "stdin", _FakeStdin([PAYLOAD]))

    payload = render_thin._consume_stdin()

    assert render_thin._extract_session_id(payload) == "abc-123"


@pytest.mark.parametrize("buf,expected", [
    (bytearray(b'{"a": 1}'), True),
    (bytearray(b'{"a": 1'), False),
    (bytearray(b'{"a": 1}\n'), True),
    (bytearray(b''), False),
])
def test_payload_completeness_check(buf, expected):
    assert render_thin._payload_is_complete(buf) is expected


def test_session_env_injection_includes_columns(monkeypatch):
    monkeypatch.setenv("COLUMNS", "41")
    stamped = json.loads(render_thin._inject_session_env(PAYLOAD))
    assert stamped["_cs_env"]["COLUMNS"] == "41"


def test_cached_output_clips_after_displacement_suffix(tmp_path, monkeypatch, capsys):
    rendered = tmp_path / "rendered.ansi"
    meta = tmp_path / "meta.json"
    rendered.write_text("1234567890\n", encoding="utf-8")
    monkeypatch.setattr(render_thin, "_consume_stdin", lambda: None)
    monkeypatch.setattr(render_thin, "_session_paths",
                        lambda _sid: (tmp_path, rendered, meta))
    monkeypatch.setattr(render_thin, "_read_meta", lambda _path: {})
    monkeypatch.setattr(render_thin, "_is_fresh", lambda _meta: True)
    monkeypatch.setattr(render_thin, "_displacement_suffix", lambda: " SUFFIX")
    monkeypatch.setenv("COLUMNS", "8")

    assert render_thin.render() == 0
    assert capsys.readouterr().out == "1234567…\n"
