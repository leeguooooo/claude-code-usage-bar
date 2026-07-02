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
# Per-session render (v3.3.0+)
# ---------------------------------------------------------------------------
def test_render_session_writes_per_session_files(monkeypatch, tmp_path: Path):
    """_render_session must write rendered.ansi + meta.json into the
    per-session subdir, not the legacy top-level paths."""
    monkeypatch.setattr(_d, "_cache_dir", lambda: tmp_path)
    sid = "abcd-1234"
    sdir = tmp_path / "sessions" / sid
    sdir.mkdir(parents=True)
    (sdir / "last_stdin.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(_d, "_render_payload", lambda payload: "FAKE LINE")

    assert _d._render_session(sid) is True
    rendered = sdir / "rendered.ansi"
    meta = sdir / "rendered.meta.json"
    assert rendered.read_text() == "FAKE LINE\n"
    m = json.loads(meta.read_text())
    assert m["session_id"] == sid
    assert m["pid"] == os.getpid()


def test_active_sessions_lists_recent_buckets(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(_d, "_cache_dir", lambda: tmp_path)
    sroot = tmp_path / "sessions"
    sroot.mkdir(parents=True)
    fresh = sroot / "fresh-sid"
    fresh.mkdir()
    (fresh / "last_stdin.json").write_text("{}", encoding="utf-8")
    # Stale: mtime > GC threshold
    stale = sroot / "stale-sid"
    stale.mkdir()
    p = stale / "last_stdin.json"
    p.write_text("{}", encoding="utf-8")
    old = time.time() - (_d.SESSION_GC_AFTER_S + 60)
    os.utime(p, (old, old))

    sids = _d._active_sessions()
    assert "fresh-sid" in sids
    assert "stale-sid" not in sids


def test_active_sessions_skips_idle_buckets_before_gc(monkeypatch, tmp_path: Path):
    """A Claude window that stopped ticking must not stay in the daemon's
    1Hz render set until the 24h GC window expires."""
    monkeypatch.setattr(_d, "_cache_dir", lambda: tmp_path)
    sroot = tmp_path / "sessions"
    sroot.mkdir(parents=True)
    active = sroot / "active-sid"
    active.mkdir()
    (active / "last_stdin.json").write_text("{}", encoding="utf-8")
    idle = sroot / "idle-sid"
    idle.mkdir()
    p = idle / "last_stdin.json"
    p.write_text("{}", encoding="utf-8")
    old = time.time() - (_d.ACTIVE_SESSION_AFTER_S + 1)
    os.utime(p, (old, old))

    sids = _d._active_sessions()

    assert "active-sid" in sids
    assert "idle-sid" not in sids


def test_session_dir_sanitises_session_id(monkeypatch, tmp_path: Path):
    """Defensive: a malicious session_id with path traversal must not
    escape sessions/ directory."""
    monkeypatch.setattr(_d, "_cache_dir", lambda: tmp_path)
    d = _d.session_dir("../../etc/passwd")
    # Result must be inside sessions/, not the literal traversal path.
    assert (tmp_path / "sessions") in d.parents


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


def test_thin_client_does_not_signal_daemon_for_age_stale_meta(monkeypatch, tmp_path: Path):
    """A slow session render can make one bucket older than stale_after.
    That should fall back and spawn-if-dead, not kill the shared daemon."""
    _setup_session_paths(monkeypatch, tmp_path)
    sdir = tmp_path / "sessions" / "default"
    sdir.mkdir(parents=True)
    (sdir / "rendered.ansi").write_text("old\n", encoding="utf-8")
    (sdir / "rendered.meta.json").write_text(json.dumps({
        "generated_at": time.time() - 30.0,
        "stale_after_seconds": 5.0,
        "daemon_started_at": time.time(),
        "pid": 12345,
    }), encoding="utf-8")

    signalled = []
    monkeypatch.setattr(render_thin, "_signal_outdated_daemon", lambda meta: signalled.append(meta))
    monkeypatch.setattr(render_thin, "_spawn_daemon_async", lambda: None)
    monkeypatch.setattr(render_thin, "_fallback_inline", lambda: 0)

    assert render_thin.render() == 0
    assert signalled == []


def test_thin_client_handles_missing_fields():
    assert render_thin._is_fresh({}) is False
    assert render_thin._is_fresh({"generated_at": "not-a-number"}) is False


def test_thin_client_read_meta_missing(tmp_path: Path):
    assert render_thin._read_meta(tmp_path / "nope.json") is None


def test_thin_client_read_meta_corrupt(tmp_path: Path):
    p = tmp_path / "meta.json"
    p.write_text("not json", encoding="utf-8")
    assert render_thin._read_meta(p) is None


def _setup_session_paths(monkeypatch, tmp_path: Path):
    """Common helper: rebase render_thin's cache + sessions root to tmp_path."""
    monkeypatch.setattr(render_thin, "_CACHE_DIR", tmp_path)
    monkeypatch.setattr(render_thin, "_SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(render_thin, "_LEGACY_STDIN_CACHE", tmp_path / "last_stdin.json")
    # Point the displacement check at a non-existent file by default so the
    # warning suffix tests stay isolated from the developer's real
    # ~/.claude/settings.json (which may itself be displaced).
    monkeypatch.setattr(render_thin, "_USER_SETTINGS", tmp_path / "no-such-settings.json")


# ---------------------------------------------------------------------------
# Thin client end-to-end: fresh daemon output → fast path (no core import)
# ---------------------------------------------------------------------------
def test_thin_client_fast_path_prints_rendered(monkeypatch, tmp_path: Path, capsys):
    """When meta is fresh, cs render must just write the per-session
    rendered.ansi to stdout."""
    _setup_session_paths(monkeypatch, tmp_path)
    sid = "test-session"
    sdir = tmp_path / "sessions" / sid
    sdir.mkdir(parents=True)
    (sdir / "rendered.ansi").write_text("FAKE STATUS LINE\n", encoding="utf-8")
    (sdir / "rendered.meta.json").write_text(json.dumps({
        "generated_at": time.time(),
        "stale_after_seconds": 5.0,
        "pid": 9999,
    }), encoding="utf-8")

    payload = json.dumps({"session_id": sid}).encode()
    monkeypatch.setattr(render_thin, "_consume_stdin", lambda: payload)

    rc = render_thin.render()
    out = capsys.readouterr().out
    assert rc == 0
    assert out == "FAKE STATUS LINE\n"


def test_thin_client_appends_displacement_warning(monkeypatch, tmp_path: Path, capsys):
    """When ~/.claude/settings.json statusLine points at someone else's
    binary, cs render must append a one-line warning so the user notices
    their global bar got hijacked (e.g. by open-island). This only fires
    in projects where cs is still wired up via a project-level override —
    in those projects the bar still renders, and the suffix is the only
    feedback channel we have."""
    _setup_session_paths(monkeypatch, tmp_path)
    sid = "displaced-sid"
    sdir = tmp_path / "sessions" / sid
    sdir.mkdir(parents=True)
    (sdir / "rendered.ansi").write_text("FAKE BAR\n", encoding="utf-8")
    (sdir / "rendered.meta.json").write_text(json.dumps({
        "generated_at": time.time(),
        "stale_after_seconds": 5.0,
    }), encoding="utf-8")

    foreign_settings = tmp_path / "foreign-settings.json"
    foreign_settings.write_text(json.dumps({
        "statusLine": {
            "type": "command",
            "command": "/Users/leo/.open-island/bin/open-island-statusline",
        }
    }), encoding="utf-8")
    monkeypatch.setattr(render_thin, "_USER_SETTINGS", foreign_settings)

    payload = json.dumps({"session_id": sid}).encode()
    monkeypatch.setattr(render_thin, "_consume_stdin", lambda: payload)

    rc = render_thin.render()
    out = capsys.readouterr().out
    assert rc == 0
    assert "FAKE BAR" in out
    assert "open-island-statusline" in out
    assert "cs --setup" in out
    # Suffix must land on the same line as the bar — exactly one newline.
    assert out.count("\n") == 1


def test_thin_client_no_warning_when_ours(monkeypatch, tmp_path: Path, capsys):
    _setup_session_paths(monkeypatch, tmp_path)
    sid = "happy-sid"
    sdir = tmp_path / "sessions" / sid
    sdir.mkdir(parents=True)
    (sdir / "rendered.ansi").write_text("FAKE BAR\n", encoding="utf-8")
    (sdir / "rendered.meta.json").write_text(json.dumps({
        "generated_at": time.time(),
        "stale_after_seconds": 5.0,
    }), encoding="utf-8")
    own = tmp_path / "own-settings.json"
    own.write_text(json.dumps({
        "statusLine": {"type": "command", "command": "/usr/local/bin/cs render"}
    }), encoding="utf-8")
    monkeypatch.setattr(render_thin, "_USER_SETTINGS", own)

    payload = json.dumps({"session_id": sid}).encode()
    monkeypatch.setattr(render_thin, "_consume_stdin", lambda: payload)
    render_thin.render()
    out = capsys.readouterr().out
    assert out == "FAKE BAR\n"


def test_thin_client_no_warning_when_settings_missing(monkeypatch, tmp_path: Path, capsys):
    _setup_session_paths(monkeypatch, tmp_path)
    sid = "missing-sid"
    sdir = tmp_path / "sessions" / sid
    sdir.mkdir(parents=True)
    (sdir / "rendered.ansi").write_text("FAKE BAR\n", encoding="utf-8")
    (sdir / "rendered.meta.json").write_text(json.dumps({
        "generated_at": time.time(),
        "stale_after_seconds": 5.0,
    }), encoding="utf-8")
    # _USER_SETTINGS already monkey-patched to a non-existent path in setup.
    payload = json.dumps({"session_id": sid}).encode()
    monkeypatch.setattr(render_thin, "_consume_stdin", lambda: payload)
    render_thin.render()
    out = capsys.readouterr().out
    assert out == "FAKE BAR\n"


def test_thin_client_no_warning_when_settings_corrupt(monkeypatch, tmp_path: Path, capsys):
    """A malformed settings.json must not crash the render path."""
    _setup_session_paths(monkeypatch, tmp_path)
    sid = "corrupt-sid"
    sdir = tmp_path / "sessions" / sid
    sdir.mkdir(parents=True)
    (sdir / "rendered.ansi").write_text("FAKE BAR\n", encoding="utf-8")
    (sdir / "rendered.meta.json").write_text(json.dumps({
        "generated_at": time.time(),
        "stale_after_seconds": 5.0,
    }), encoding="utf-8")
    bad = tmp_path / "bad.json"
    bad.write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(render_thin, "_USER_SETTINGS", bad)
    payload = json.dumps({"session_id": sid}).encode()
    monkeypatch.setattr(render_thin, "_consume_stdin", lambda: payload)
    render_thin.render()
    out = capsys.readouterr().out
    assert out == "FAKE BAR\n"


def test_thin_client_forwards_stdin_to_per_session_cache(monkeypatch, tmp_path: Path):
    """v3.3.0 critical: the thin client must persist stdin to PER-SESSION
    last_stdin.json so the daemon renders this session's data, not whatever
    other window most recently called cs render."""
    _setup_session_paths(monkeypatch, tmp_path)
    sid_a = "session-aaa"
    sid_b = "session-bbb"

    payload_a = json.dumps({"session_id": sid_a, "marker": "A"}).encode()
    payload_b = json.dumps({"session_id": sid_b, "marker": "B"}).encode()

    monkeypatch.setattr(render_thin, "_spawn_daemon_async", lambda: None)
    monkeypatch.setattr(render_thin, "_fallback_inline", lambda: 0)

    # Simulate window A then window B both calling cs render.
    monkeypatch.setattr(render_thin, "_consume_stdin", lambda: payload_a)
    render_thin.render()
    monkeypatch.setattr(render_thin, "_consume_stdin", lambda: payload_b)
    render_thin.render()

    # Both must have their own bucket; B did NOT overwrite A's stdin.
    # render_thin stamps `_cs_env` into the payload, so compare content minus it.
    def _without_env(b: bytes) -> dict:
        d = json.loads(b)
        d.pop("_cs_env", None)
        return d

    a_stdin = tmp_path / "sessions" / sid_a / "last_stdin.json"
    b_stdin = tmp_path / "sessions" / sid_b / "last_stdin.json"
    assert _without_env(a_stdin.read_bytes()) == json.loads(payload_a), (
        "session A's stdin was overwritten — multi-session race not fixed"
    )
    assert _without_env(b_stdin.read_bytes()) == json.loads(payload_b)


def test_thin_client_fallback_when_meta_stale(monkeypatch, tmp_path: Path):
    """Stale meta → must NOT use rendered.ansi, must call inline fallback."""
    _setup_session_paths(monkeypatch, tmp_path)
    sid = "stale-sid"
    sdir = tmp_path / "sessions" / sid
    sdir.mkdir(parents=True)
    (sdir / "rendered.ansi").write_text("STALE GARBAGE\n", encoding="utf-8")
    (sdir / "rendered.meta.json").write_text(json.dumps({
        "generated_at": time.time() - 60.0,
        "stale_after_seconds": 5.0,
    }), encoding="utf-8")
    payload = json.dumps({"session_id": sid}).encode()
    monkeypatch.setattr(render_thin, "_consume_stdin", lambda: payload)

    fallback_called, spawn_called = [], []
    monkeypatch.setattr(render_thin, "_fallback_inline",
                        lambda: (fallback_called.append(True), 0)[1])
    monkeypatch.setattr(render_thin, "_spawn_daemon_async",
                        lambda: spawn_called.append(True))

    rc = render_thin.render()
    assert rc == 0
    assert fallback_called == [True]
    assert spawn_called == [True]


def test_thin_client_fallback_when_no_meta(monkeypatch, tmp_path: Path):
    _setup_session_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(render_thin, "_consume_stdin", lambda: None)
    fallback_called = []
    monkeypatch.setattr(render_thin, "_fallback_inline",
                        lambda: (fallback_called.append(True), 0)[1])
    monkeypatch.setattr(render_thin, "_spawn_daemon_async", lambda: None)
    assert render_thin.render() == 0
    assert fallback_called == [True]


def test_fallback_inline_appends_displacement_warning(monkeypatch, tmp_path: Path, capsys):
    """The inline fallback path (daemon dead / no fresh meta) must also
    surface the displacement warning. We stub core.main to print a known
    string, then assert the suffix is spliced in."""
    foreign = tmp_path / "foreign.json"
    foreign.write_text(json.dumps({
        "statusLine": {"type": "command", "command": "other-tool-bin"}
    }), encoding="utf-8")
    monkeypatch.setattr(render_thin, "_USER_SETTINGS", foreign)

    def fake_core_main():
        sys.stdout.write("FAKE INLINE BAR\n")

    import claude_statusbar.core as _core
    monkeypatch.setattr(_core, "main", fake_core_main)

    render_thin._fallback_inline()
    out = capsys.readouterr().out
    assert "FAKE INLINE BAR" in out
    assert "other-tool-bin" in out
    assert "cs --setup" in out
    assert out.count("\n") == 1


def test_fallback_inline_passthrough_when_not_displaced(monkeypatch, tmp_path: Path, capsys):
    own = tmp_path / "own.json"
    own.write_text(json.dumps({
        "statusLine": {"type": "command", "command": "cs render"}
    }), encoding="utf-8")
    monkeypatch.setattr(render_thin, "_USER_SETTINGS", own)

    def fake_core_main():
        sys.stdout.write("FAKE INLINE BAR\n")

    import claude_statusbar.core as _core
    monkeypatch.setattr(_core, "main", fake_core_main)

    render_thin._fallback_inline()
    out = capsys.readouterr().out
    assert out == "FAKE INLINE BAR\n"


def test_thin_client_fallback_replays_stdin_for_core_main(monkeypatch, tmp_path: Path):
    _setup_session_paths(monkeypatch, tmp_path)
    payload = b'{"session_id": "x", "hello": "world"}'
    monkeypatch.setattr(render_thin, "_consume_stdin", lambda: payload)
    monkeypatch.setattr(render_thin, "_spawn_daemon_async", lambda: None)

    seen = {}
    def fake_inline():
        seen["stdin"] = sys.stdin.read()
        return 0
    monkeypatch.setattr(render_thin, "_fallback_inline", fake_inline)

    render_thin.render()
    assert seen["stdin"] == payload.decode(), (
        f"fallback path must see replayed stdin; got {seen.get('stdin')!r}"
    )


def test_extract_session_id_handles_missing_field():
    """Old Claude Code versions or malformed payloads → fall back to "default"
    bucket so the daemon still renders something."""
    assert render_thin._extract_session_id(b"{}") == "default"
    assert render_thin._extract_session_id(b"not-json") == "default"
    assert render_thin._extract_session_id(b'{"session_id": "abc-123"}') == "abc-123"


def test_extract_session_id_rejects_non_string_types():
    """S3 from codex review: explicit type check prevents falsy-but-valid
    integer/null session_ids from collapsing into 'default' silently."""
    assert render_thin._extract_session_id(b'{"session_id": null}') == "default"
    assert render_thin._extract_session_id(b'{"session_id": 0}') == "default"
    assert render_thin._extract_session_id(b'{"session_id": ""}') == "default"
    assert render_thin._extract_session_id(b'{"session_id": "   "}') == "default"
    assert render_thin._extract_session_id(b'{"session_id": ["a"]}') == "default"


# ---------------------------------------------------------------------------
# Codex review S4: cross-session content isolation
# ---------------------------------------------------------------------------
def test_thin_client_serves_correct_session_when_multiple_exist(
    monkeypatch, tmp_path: Path, capsys
):
    """The most critical property of v3.3.0: when sessions A and B both
    have fresh rendered.ansi files, calling render() with payload A must
    return A's content, not B's."""
    _setup_session_paths(monkeypatch, tmp_path)
    sid_a, sid_b = "sess-aaa", "sess-bbb"
    for sid, content in [(sid_a, "AAA STATUS"), (sid_b, "BBB STATUS")]:
        sdir = tmp_path / "sessions" / sid
        sdir.mkdir(parents=True)
        (sdir / "rendered.ansi").write_text(content + "\n", encoding="utf-8")
        (sdir / "rendered.meta.json").write_text(json.dumps({
            "generated_at": time.time(),
            "stale_after_seconds": 5.0,
        }), encoding="utf-8")

    # Render with session A's payload — must see AAA, not BBB.
    monkeypatch.setattr(render_thin, "_consume_stdin",
                        lambda: json.dumps({"session_id": sid_a}).encode())
    render_thin.render()
    out_a = capsys.readouterr().out
    assert out_a == "AAA STATUS\n", f"session A served wrong content: {out_a!r}"

    # Render with session B's payload — must see BBB, not AAA.
    monkeypatch.setattr(render_thin, "_consume_stdin",
                        lambda: json.dumps({"session_id": sid_b}).encode())
    render_thin.render()
    out_b = capsys.readouterr().out
    assert out_b == "BBB STATUS\n", f"session B served wrong content: {out_b!r}"


# ---------------------------------------------------------------------------
# Codex review S5: end-to-end "default" bucket fallback
# ---------------------------------------------------------------------------
def test_thin_client_routes_missing_session_id_to_default_bucket(
    monkeypatch, tmp_path: Path, capsys
):
    """A payload without session_id must land in sessions/default/. Pre-create
    fresh content there; render() must serve it."""
    _setup_session_paths(monkeypatch, tmp_path)
    default_dir = tmp_path / "sessions" / "default"
    default_dir.mkdir(parents=True)
    (default_dir / "rendered.ansi").write_text("DEFAULT BUCKET LINE\n", encoding="utf-8")
    (default_dir / "rendered.meta.json").write_text(json.dumps({
        "generated_at": time.time(),
        "stale_after_seconds": 5.0,
    }), encoding="utf-8")

    # Payload has no session_id → router must use "default".
    payload = b'{"some_other_field": 1}'
    monkeypatch.setattr(render_thin, "_consume_stdin", lambda: payload)
    render_thin.render()
    out = capsys.readouterr().out
    assert out == "DEFAULT BUCKET LINE\n", out

    # And the stdin must have been persisted into sessions/default/.
    # render_thin stamps `_cs_env`; compare content minus it.
    persisted = json.loads((default_dir / "last_stdin.json").read_bytes())
    persisted.pop("_cs_env", None)
    assert persisted == json.loads(payload)


# ---------------------------------------------------------------------------
# Codex review N5: contract test — sanitize logic must NOT drift between
# render_thin and daemon (they're duplicated to keep render_thin import-cheap)
# ---------------------------------------------------------------------------
def test_sanitize_session_id_contract_pinned_between_modules(monkeypatch, tmp_path: Path):
    """If render_thin._sanitize_session_id and daemon.session_dir() ever
    drift, the thin client writes to one path and the daemon reads from
    another — silent breakage. Pin the contract."""
    monkeypatch.setattr(_d, "_cache_dir", lambda: tmp_path)
    cases = [
        "591dc69b-f2c8-40b0-8b52-c9f09b02e22a",  # real UUID v4
        "default",
        "../../etc/passwd",       # traversal attempt
        "",                       # empty
        "a" * 200,                # very long
        "weird@chars!?",          # punctuation
        "with spaces here",       # spaces
    ]
    for sid in cases:
        thin_safe = render_thin._sanitize_session_id(sid)
        daemon_dir = _d.session_dir(sid)
        assert daemon_dir.name == thin_safe, (
            f"sanitize drift for {sid!r}: thin → {thin_safe!r}, "
            f"daemon → {daemon_dir.name!r}"
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


def test_statusline_config_includes_default_refresh_interval():
    """v3.2.3+: default config writes refreshInterval=1 so the cache-age
    countdown actually animates out of the box."""
    from claude_statusbar.setup import DEFAULT_REFRESH_INTERVAL
    cfg = _statusline_config()
    assert cfg["refreshInterval"] == DEFAULT_REFRESH_INTERVAL == 1


def test_statusline_config_honors_explicit_refresh_interval():
    cfg = _statusline_config(refresh_interval=30)
    assert cfg["refreshInterval"] == 30


def test_ensure_statusline_preserves_explicit_refresh_interval(tmp_path: Path, monkeypatch):
    """If the user manually set refreshInterval=60, the daily auto-repair
    must NOT silently bump it to our 1s default."""
    from claude_statusbar import setup as setup_mod
    settings = tmp_path / "settings.json"
    monkeypatch.setattr(setup_mod, "SETTINGS_PATH", settings)
    settings.write_text(json.dumps({
        "statusLine": {
            "type": "command",
            "command": "/abs/path/cs",
            "refreshInterval": 60,
        },
    }), encoding="utf-8")

    setup_mod.ensure_statusline_configured(fast=False)

    after = json.loads(settings.read_text(encoding="utf-8"))
    assert after["statusLine"]["refreshInterval"] == 60, (
        f"daily auto-repair must preserve explicit refreshInterval; got "
        f"{after['statusLine'].get('refreshInterval')!r}"
    )


def test_ensure_statusline_writes_default_refresh_interval_for_new_install(tmp_path: Path, monkeypatch):
    """Fresh install (no settings.json yet): default refreshInterval=1."""
    from claude_statusbar import setup as setup_mod
    settings = tmp_path / "settings.json"
    monkeypatch.setattr(setup_mod, "SETTINGS_PATH", settings)

    setup_mod.ensure_statusline_configured(fast=False)

    after = json.loads(settings.read_text(encoding="utf-8"))
    assert after["statusLine"]["refreshInterval"] == 1


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
    monkeypatch.setattr(_d, "_render_all_sessions", lambda: 0)

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
    """MUST-FIX from codex review: the daily auto-repair (fast=None default)
    must NOT downgrade a user who already opted into `cs render`."""
    from claude_statusbar import setup as setup_mod
    settings = tmp_path / "settings.json"
    monkeypatch.setattr(setup_mod, "SETTINGS_PATH", settings)
    # User already chose fast mode previously.
    settings.write_text(json.dumps({
        "statusLine": {"type": "command", "command": "/abs/path/cs render"},
    }), encoding="utf-8")

    # Daily auto-repair tick — fast=None (preserve), the new default in 3.6.0.
    changed, message = setup_mod.ensure_statusline_configured()

    # Read what's there now.
    after = json.loads(settings.read_text(encoding="utf-8"))
    new_cmd = after["statusLine"]["command"]
    assert new_cmd.endswith(" render"), (
        f"daily auto-repair downgraded fast mode! command is now {new_cmd!r}. "
        f"changed={changed}, message={message!r}"
    )


def test_ensure_statusline_inline_explicit_downgrades(tmp_path: Path, monkeypatch):
    """fast=False is now an EXPLICIT user request to switch to inline mode,
    not a preserve-existing signal. Verify it actually downgrades."""
    from claude_statusbar import setup as setup_mod
    settings = tmp_path / "settings.json"
    monkeypatch.setattr(setup_mod, "SETTINGS_PATH", settings)
    settings.write_text(json.dumps({
        "statusLine": {"type": "command", "command": "/abs/path/cs render"},
    }), encoding="utf-8")

    changed, _ = setup_mod.ensure_statusline_configured(fast=False)

    after = json.loads(settings.read_text(encoding="utf-8"))
    assert changed is True
    assert not after["statusLine"]["command"].endswith(" render"), (
        "explicit fast=False (cs --setup --inline) should downgrade to inline"
    )


def test_render_payload_signal_alarm_aborts_slow_render(monkeypatch):
    """Codex-flagged gap: the signal.alarm timeout in _render_payload was
    never exercised by tests. Mock core.main with time.sleep > timeout and
    verify _render_payload returns None within the timeout window.

    POSIX-only (signal.alarm); skipped on Windows.
    """
    import signal as _sig
    if not hasattr(_sig, "SIGALRM"):
        import pytest
        pytest.skip("signal.alarm not available on this platform")

    import claude_statusbar.core as core_mod
    import time as _time

    # Shorten timeout so the test runs in ~1s.
    monkeypatch.setattr(_d, "RENDER_TIMEOUT_S", 1)

    def slow_core_main(**kwargs):
        _time.sleep(5)  # would exceed 1s alarm
        sys.stdout.write("LATE")

    monkeypatch.setattr(core_mod, "main", slow_core_main)

    t0 = _time.time()
    out = _d._render_payload("{}")
    elapsed = _time.time() - t0
    assert out is None, f"timeout path should return None, got {out!r}"
    # Should bail in ~1s + epsilon, not the full 5s sleep.
    assert elapsed < 3.0, f"timeout took {elapsed:.1f}s — alarm not firing"


def test_render_payload_captures_stdout(monkeypatch):
    """Daemon's _render_payload must capture core.main()'s stdout into a string.

    If core.main ever stops printing (e.g., switches to logging), the daemon
    would silently produce empty output. This test pins the contract.
    """
    captured_kwargs = {}

    def fake_core_main(**kwargs):
        captured_kwargs.update(kwargs)
        sys.stdout.write("FAKE RENDERED LINE")

    # Patch the core.main symbol the daemon imports lazily.
    import claude_statusbar.core as core_mod
    monkeypatch.setattr(core_mod, "main", fake_core_main)

    out = _d._render_payload("{}")
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


def test_gc_orphan_tmp_files(tmp_path, monkeypatch):
    import time
    import claude_statusbar.daemon as daemon
    monkeypatch.setattr(daemon, "_cache_dir", lambda: tmp_path)
    old = tmp_path / ".last_stdin.json.abc123.tmp"
    old.write_text("")
    import os
    os.utime(old, (time.time() - 7200, time.time() - 7200))
    fresh = tmp_path / ".last_stdin.json.def456.tmp"
    fresh.write_text("")
    keeper = tmp_path / "rate_latest.json"          # non-tmp: untouched
    keeper.write_text("{}")
    daemon._gc_orphan_tmp_files()
    assert not old.exists()
    assert fresh.exists()                            # younger than 1h: kept
    assert keeper.exists()


def test_ip_heartbeat_gated_on_show_ip_risk(tmp_path, monkeypatch):
    """The daemon's egress-IP probe heartbeat must NOT fire when the user
    hasn't enabled show_ip_risk — default users make zero third-party calls."""
    import claude_statusbar.ip_risk as ip_risk
    import claude_statusbar.config as config
    calls = []
    monkeypatch.setattr(ip_risk, "ensure_fresh", lambda *a, **k: calls.append(1))

    # Mirror the daemon's gate: only probe when show_ip_risk is on.
    def _tick(cfg_on):
        monkeypatch.setattr(config, "load_config",
                            lambda *a, **k: config.StatusbarConfig(show_ip_risk=cfg_on))
        if config.load_config().show_ip_risk:
            ip_risk.ensure_fresh()

    _tick(False)
    assert calls == []          # default off → no probe
    _tick(True)
    assert calls == [1]         # opt-in → probes
