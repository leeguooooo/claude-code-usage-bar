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
    monkeypatch.setattr(render_thin, "_consume_stdin", lambda: None)

    rc = render_thin.render()
    out = capsys.readouterr().out
    assert rc == 0
    assert out == "FAKE STATUS LINE\n"


def test_thin_client_forwards_stdin_to_cache(monkeypatch, tmp_path: Path, capsys):
    """Critical Phase B regression: the thin client MUST persist stdin so
    the daemon sees fresh rate_limits on its next tick. Without this the
    7d% / 5h% counters freeze the moment fast-mode is enabled."""
    rendered = tmp_path / "rendered.ansi"
    meta = tmp_path / "rendered.meta.json"
    cache = tmp_path / "last_stdin.json"
    rendered.write_text("X\n", encoding="utf-8")
    meta.write_text(json.dumps({
        "generated_at": time.time(),
        "stale_after_seconds": 5.0,
    }), encoding="utf-8")
    monkeypatch.setattr(render_thin, "_RENDERED", rendered)
    monkeypatch.setattr(render_thin, "_META", meta)
    monkeypatch.setattr(render_thin, "_CACHE_DIR", tmp_path)
    monkeypatch.setattr(render_thin, "_LAST_STDIN_CACHE", cache)

    fresh_payload = b'{"rate_limits": {"seven_day": {"used_percentage": 79}}}'
    monkeypatch.setattr(render_thin, "_consume_stdin", lambda: fresh_payload)

    render_thin.render()
    assert cache.exists(), "thin client must write stdin to last_stdin.json"
    assert cache.read_bytes() == fresh_payload


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
    monkeypatch.setattr(render_thin, "_consume_stdin", lambda: None)

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
    monkeypatch.setattr(render_thin, "_consume_stdin", lambda: None)
    fallback_called = []
    monkeypatch.setattr(render_thin, "_fallback_inline",
                        lambda: (fallback_called.append(True), 0)[1])
    monkeypatch.setattr(render_thin, "_spawn_daemon_async", lambda: None)
    assert render_thin.render() == 0
    assert fallback_called == [True]


def test_thin_client_fallback_replays_stdin_for_core_main(monkeypatch, tmp_path: Path):
    """When falling back to inline render, the captured stdin bytes must be
    replayed into sys.stdin so core.main()'s parse_stdin_data() sees them."""
    monkeypatch.setattr(render_thin, "_RENDERED", tmp_path / "nope.ansi")
    monkeypatch.setattr(render_thin, "_META", tmp_path / "nope.json")
    monkeypatch.setattr(render_thin, "_CACHE_DIR", tmp_path)
    monkeypatch.setattr(render_thin, "_LAST_STDIN_CACHE", tmp_path / "ls.json")
    monkeypatch.setattr(render_thin, "_consume_stdin", lambda: b'{"hello": "world"}')
    monkeypatch.setattr(render_thin, "_spawn_daemon_async", lambda: None)

    seen = {}
    def fake_inline():
        seen["stdin"] = sys.stdin.read()
        return 0
    monkeypatch.setattr(render_thin, "_fallback_inline", fake_inline)

    render_thin.render()
    assert seen["stdin"] == '{"hello": "world"}', (
        f"fallback path must see replayed stdin; got {seen.get('stdin')!r}"
    )


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


# ---------------------------------------------------------------------------
# Codex review fixes
# ---------------------------------------------------------------------------
def test_thin_client_treats_future_timestamp_as_stale():
    """Clock skew defense: generated_at in the future must NOT be 'fresh'.

    Without this, an NTP backward-correction freezes stale daemon output
    until wall clock catches up.
    """
    future = time.time() + 60.0  # 1 minute in the future
    assert render_thin._is_fresh(
        {"generated_at": future, "stale_after_seconds": 5.0}
    ) is False


def test_running_global_is_reset_per_run_forever_call(monkeypatch, tmp_path: Path):
    """An in-process restart (after a previous SIGTERM cleared _running)
    must NOT exit immediately on the next run_forever() call.

    We don't actually loop here — we just verify the flag gets reset.
    """
    monkeypatch.setattr(_d, "_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(_d, "_render_once", lambda: None)  # nothing to publish

    _d._running = False  # simulate previous shutdown
    # Patch acquire to fail immediately so run_forever returns without
    # actually entering the sleep loop. We're only checking the reset.
    monkeypatch.setattr(_d, "_acquire_pidfile", lambda: False)
    rc = _d.run_forever(render_interval=0.01)
    assert rc == 1  # acquire failed
    assert _d._running is True, (
        "run_forever() must reset _running=True at entry; otherwise the next "
        "in-process daemon start exits before doing any work"
    )


def test_existing_uses_render_detects_fast_mode():
    from claude_statusbar.setup import _existing_uses_render
    assert _existing_uses_render({"command": "cs render"}) is True
    assert _existing_uses_render({"command": "/usr/local/bin/cs render"}) is True
    assert _existing_uses_render({"command": "cs"}) is False
    assert _existing_uses_render({"command": "/usr/local/bin/cs"}) is False
    assert _existing_uses_render({}) is False
    assert _existing_uses_render(None) is False


def test_ensure_statusline_preserves_fast_mode(tmp_path: Path, monkeypatch):
    """MUST-FIX from codex review: the daily auto-repair (default fast=False)
    must NOT downgrade a user who already opted into `cs render`."""
    from claude_statusbar import setup as setup_mod
    settings = tmp_path / "settings.json"
    monkeypatch.setattr(setup_mod, "SETTINGS_PATH", settings)
    # User already chose fast mode previously.
    settings.write_text(json.dumps({
        "statusLine": {"type": "command", "command": "/abs/path/cs render"},
    }), encoding="utf-8")

    # Daily auto-repair tick — default fast=False.
    changed, message = setup_mod.ensure_statusline_configured(fast=False)

    # Read what's there now.
    after = json.loads(settings.read_text(encoding="utf-8"))
    new_cmd = after["statusLine"]["command"]
    assert new_cmd.endswith(" render"), (
        f"daily auto-repair downgraded fast mode! command is now {new_cmd!r}. "
        f"changed={changed}, message={message!r}"
    )


def test_render_once_captures_stdout(monkeypatch, tmp_path: Path):
    """Daemon's _render_once must capture core.main()'s stdout into a string.

    If core.main ever stops printing (e.g., switches to logging), the daemon
    would silently produce empty output. This test pins the contract.
    """
    monkeypatch.setattr(_d, "_cache_dir", lambda: tmp_path)
    (tmp_path / "last_stdin.json").write_text("{}", encoding="utf-8")

    captured_kwargs = {}

    def fake_core_main(**kwargs):
        captured_kwargs.update(kwargs)
        sys.stdout.write("FAKE RENDERED LINE")

    # Patch the core.main symbol the daemon imports lazily.
    import claude_statusbar.core as core_mod
    monkeypatch.setattr(core_mod, "main", fake_core_main)

    out = _d._render_once()
    assert out == "FAKE RENDERED LINE", f"capture failed; got {out!r}"
    assert captured_kwargs.get("_suppress_side_effects") is True, (
        "daemon must call core.main with _suppress_side_effects=True so it "
        "doesn't fire auto-update / settings-repair 60×/min"
    )


def test_suppress_side_effects_skips_update_check(monkeypatch, tmp_path: Path):
    """_suppress_side_effects=True must skip both check_for_updates and
    _maybe_ensure_statusline (the daemon path runs them on its own cadence)."""
    import claude_statusbar.core as core_mod
    update_calls = []
    statusline_calls = []
    monkeypatch.setattr(core_mod, "check_for_updates",
                        lambda *a, **kw: update_calls.append(True))
    monkeypatch.setattr(core_mod, "_maybe_ensure_statusline",
                        lambda *a, **kw: statusline_calls.append(True))

    # Pipe a minimal stdin payload.
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
    try:
        core_mod.main(_suppress_side_effects=True)
    except Exception:
        # The render path may fail because we mocked things — that's OK.
        # We're only checking the side-effect guard here.
        pass
    assert update_calls == [], "_suppress_side_effects must skip check_for_updates"
    assert statusline_calls == [], (
        "_suppress_side_effects must skip _maybe_ensure_statusline"
    )


# Helper imports for the side-effects test
import io  # noqa: E402
