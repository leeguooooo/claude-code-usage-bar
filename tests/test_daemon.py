"""Daemon + thin-client integration tests (Phase B).

These exercise the cheap interfaces of daemon.py / render_thin.py without
actually fork/exec'ing a real daemon. The goal is to catch regressions in:

- pidfile read/write semantics
- meta.json freshness arithmetic
- thin client's fast-path / fallback decision
- statusLine recognition for `cs render` (vs bare `cs`)
"""

import json
import os
import sys
import time
from pathlib import Path

import pytest

from claude_statusbar import daemon as _d
from claude_statusbar import render_thin
from claude_statusbar.setup import (
    _is_our_statusline,
    _statusline_config,
)


# ---------------------------------------------------------------------------
# Pidfile / liveness
# ---------------------------------------------------------------------------
def test_read_pidfile_missing(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(_d, "_cache_dir", lambda: tmp_path)
    assert _d.read_pidfile() is None


def test_read_pidfile_writes_and_reads(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(_d, "_cache_dir", lambda: tmp_path)
    (tmp_path / "daemon.pid").write_text("12345\n", encoding="utf-8")
    assert _d.read_pidfile() == 12345


def test_read_pidfile_handles_garbage(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(_d, "_cache_dir", lambda: tmp_path)
    (tmp_path / "daemon.pid").write_text("not-a-number", encoding="utf-8")
    assert _d.read_pidfile() is None


def test_is_alive_for_self():
    assert _d.is_alive(os.getpid()) is True


def test_is_alive_for_dead_pid():
    # PID 1 obviously alive; pick a very high PID unlikely to exist.
    assert _d.is_alive(999_999_999) is False


# ---------------------------------------------------------------------------
# Atomic publish / meta freshness
# ---------------------------------------------------------------------------
def test_publish_writes_both_files(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(_d, "_cache_dir", lambda: tmp_path)
    _d._publish("hello world")
    assert (tmp_path / "rendered.ansi").read_text(encoding="utf-8") == "hello world\n"
    meta = json.loads((tmp_path / "rendered.meta.json").read_text(encoding="utf-8"))
    assert meta["pid"] == os.getpid()
    assert meta["stale_after_seconds"] == _d.META_STALE_AFTER
    assert abs(meta["generated_at"] - time.time()) < 5.0


# ---------------------------------------------------------------------------
# Thin client: freshness gate
# ---------------------------------------------------------------------------
def test_thin_client_is_fresh_recent_meta():
    now = time.time()
    assert render_thin._is_fresh({"generated_at": now, "stale_after_seconds": 5.0}) is True


def test_thin_client_stale_meta():
    now = time.time()
    assert render_thin._is_fresh(
        {"generated_at": now - 30.0, "stale_after_seconds": 5.0}
    ) is False


def test_thin_client_handles_missing_fields():
    assert render_thin._is_fresh({}) is False
    assert render_thin._is_fresh({"generated_at": "not-a-number"}) is False


def test_thin_client_read_meta_missing(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(render_thin, "_META", tmp_path / "nope.json")
    assert render_thin._read_meta() is None


def test_thin_client_read_meta_corrupt(monkeypatch, tmp_path: Path):
    p = tmp_path / "meta.json"
    p.write_text("not json", encoding="utf-8")
    monkeypatch.setattr(render_thin, "_META", p)
    assert render_thin._read_meta() is None


# ---------------------------------------------------------------------------
# Thin client end-to-end: fresh daemon output → fast path (no core import)
# ---------------------------------------------------------------------------
def test_thin_client_fast_path_prints_rendered(monkeypatch, tmp_path: Path, capsys):
    """When meta is fresh, cs render must just write rendered.ansi to stdout."""
    rendered = tmp_path / "rendered.ansi"
    meta = tmp_path / "rendered.meta.json"
    rendered.write_text("FAKE STATUS LINE\n", encoding="utf-8")
    meta.write_text(json.dumps({
        "generated_at": time.time(),
        "stale_after_seconds": 5.0,
        "pid": 9999,
    }), encoding="utf-8")
    monkeypatch.setattr(render_thin, "_RENDERED", rendered)
    monkeypatch.setattr(render_thin, "_META", meta)

    rc = render_thin.render()
    out = capsys.readouterr().out
    assert rc == 0
    assert out == "FAKE STATUS LINE\n"


def test_thin_client_fallback_when_meta_stale(monkeypatch, tmp_path: Path):
    """Stale meta → must NOT use rendered.ansi, must call inline fallback."""
    rendered = tmp_path / "rendered.ansi"
    meta = tmp_path / "rendered.meta.json"
    rendered.write_text("STALE GARBAGE\n", encoding="utf-8")
    meta.write_text(json.dumps({
        "generated_at": time.time() - 60.0,  # 1 minute ago
        "stale_after_seconds": 5.0,
    }), encoding="utf-8")
    monkeypatch.setattr(render_thin, "_RENDERED", rendered)
    monkeypatch.setattr(render_thin, "_META", meta)

    fallback_called = []
    spawn_called = []
    monkeypatch.setattr(render_thin, "_fallback_inline",
                        lambda: (fallback_called.append(True), 0)[1])
    monkeypatch.setattr(render_thin, "_spawn_daemon_async",
                        lambda: spawn_called.append(True))

    rc = render_thin.render()
    assert rc == 0
    assert fallback_called == [True], "stale meta should hit inline fallback"
    assert spawn_called == [True], "stale meta should kick off lazy daemon spawn"


def test_thin_client_fallback_when_no_meta(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(render_thin, "_RENDERED", tmp_path / "nope.ansi")
    monkeypatch.setattr(render_thin, "_META", tmp_path / "nope.json")
    fallback_called = []
    monkeypatch.setattr(render_thin, "_fallback_inline",
                        lambda: (fallback_called.append(True), 0)[1])
    monkeypatch.setattr(render_thin, "_spawn_daemon_async", lambda: None)
    assert render_thin.render() == 0
    assert fallback_called == [True]


# ---------------------------------------------------------------------------
# settings.json: cs render must be recognized as ours
# ---------------------------------------------------------------------------
def test_is_our_statusline_recognizes_cs_render():
    assert _is_our_statusline({"type": "command", "command": "cs render"}) is True
    assert _is_our_statusline({"type": "command", "command": "/usr/local/bin/cs render"}) is True


def test_is_our_statusline_still_recognizes_bare_cs():
    assert _is_our_statusline({"type": "command", "command": "cs"}) is True
    assert _is_our_statusline({"type": "command", "command": "/Users/x/.local/bin/cs"}) is True


def test_is_our_statusline_rejects_foreign_command():
    assert _is_our_statusline({"type": "command", "command": "/bin/cat"}) is False
    assert _is_our_statusline({"type": "command", "command": "starship prompt"}) is False


def test_statusline_config_fast_appends_render():
    cfg = _statusline_config(fast=True)
    assert cfg["command"].endswith(" render"), \
        f"fast mode must end with ' render', got {cfg['command']!r}"


def test_statusline_config_default_no_render():
    cfg = _statusline_config(fast=False)
    assert not cfg["command"].endswith(" render")
