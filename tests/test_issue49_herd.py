"""Issue #49 — fast-daemon multi-session collapse.

The failure chain: the daemon renders active sessions serially inside a fixed
5s freshness window; on a loaded machine the batch slips past the window with
no single session being pathological, every 1Hz thin client flips to inline
rendering at once, and the resulting herd (observed live: 14-16 concurrent
`cs render`) starves the daemon further. Four defenses, each tested here:

1. daemon: the advertised stale window scales with the actual batch duration
   (`_current_stale_after`), capped so a wedged daemon is still detected.
2. daemon: the render interval stretches under machine load
   (`_effective_interval`) instead of adding fuel at 1Hz.
3. daemon: a session that keeps blowing SLOW_RENDER_S is backed off
   exponentially instead of aging the whole batch (circuit breaker), and
   fast sessions render first so a slow tail can't age them.
4. thin client: stale-but-recent output is served as-is (stale-while-
   revalidate) instead of triggering inline; true inline renders are capped
   machine-wide by flock slots, and over-cap clients serve the last render.
"""
import json
import os
import time
from pathlib import Path

import pytest

from claude_statusbar import daemon as _d
from claude_statusbar import render_thin


@pytest.fixture(autouse=True)
def _reset_daemon_pacing_state(monkeypatch):
    """Each test starts from a clean pacing slate (module-level dicts)."""
    monkeypatch.setattr(_d, "_last_batch_s", 0.0)
    monkeypatch.setattr(_d, "_render_ema", {})
    monkeypatch.setattr(_d, "_slow_streak", {})
    monkeypatch.setattr(_d, "_skip_until", {})
    monkeypatch.setattr(_d, "_log", lambda *a, **k: None)
    # A fresh render_thin slot handle per test.
    monkeypatch.setattr(render_thin, "_inline_slot_fh", None)


def _setup_session_paths(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(render_thin, "_CACHE_DIR", tmp_path)
    monkeypatch.setattr(render_thin, "_SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(render_thin, "_LEGACY_STDIN_CACHE", tmp_path / "last_stdin.json")
    monkeypatch.setattr(render_thin, "_SPAWN_MARKER", tmp_path / "daemon.spawn")
    monkeypatch.setattr(render_thin, "_USER_SETTINGS", tmp_path / "no-such-settings.json")


def _write_session(tmp_path: Path, sid: str, *, ansi="LAST GOOD BAR\n",
                   age: float, stale_after: float = 5.0):
    sdir = tmp_path / "sessions" / sid
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "rendered.ansi").write_text(ansi, encoding="utf-8")
    (sdir / "rendered.meta.json").write_text(json.dumps({
        "generated_at": time.time() - age,
        "stale_after_seconds": stale_after,
        "daemon_started_at": time.time(),  # today's daemon, today's code
        "pid": os.getpid(),
    }), encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Adaptive stale window
# ---------------------------------------------------------------------------
def test_stale_after_floors_at_classic_window(monkeypatch):
    monkeypatch.setattr(_d, "_last_batch_s", 0.1)
    assert _d._current_stale_after(1.0) == _d.META_STALE_AFTER


def test_stale_after_scales_with_batch_duration(monkeypatch):
    # A 6s batch at a 1s interval needs a window that survives one full
    # cycle of jitter: 2 * (6 + 1) = 14s.
    monkeypatch.setattr(_d, "_last_batch_s", 6.0)
    assert _d._current_stale_after(1.0) == pytest.approx(14.0)


def test_stale_after_is_capped(monkeypatch):
    # A wedged daemon must still be detected within STALE_AFTER_MAX.
    monkeypatch.setattr(_d, "_last_batch_s", 120.0)
    assert _d._current_stale_after(1.0) == _d.STALE_AFTER_MAX


def test_rendered_meta_carries_adaptive_window(monkeypatch, tmp_path: Path):
    """_render_session must publish the window it was given, so thin
    clients judge freshness by what the daemon can actually deliver."""
    monkeypatch.setenv("HOME", str(tmp_path))
    sid = "adaptive-sid"
    _d.session_stdin_path(sid).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(_d, "_render_payload", lambda payload: "BAR")
    assert _d._render_session(sid, stale_after=14.0) is True
    meta = json.loads(_d.session_meta_path(sid).read_text(encoding="utf-8"))
    assert meta["stale_after_seconds"] == pytest.approx(14.0)


# ---------------------------------------------------------------------------
# 2. Load-adaptive interval
# ---------------------------------------------------------------------------
def test_effective_interval_idle_machine_keeps_base(monkeypatch):
    monkeypatch.setattr(os, "getloadavg", lambda: (0.5, 0.5, 0.5))
    monkeypatch.setattr(os, "cpu_count", lambda: 8)
    assert _d._effective_interval(1.0) == 1.0


def test_effective_interval_stretches_under_load(monkeypatch):
    # load 2 per core → 1 + 2*(2-1) = 3× stretch.
    monkeypatch.setattr(os, "getloadavg", lambda: (16.0, 16.0, 16.0))
    monkeypatch.setattr(os, "cpu_count", lambda: 8)
    assert _d._effective_interval(1.0) == pytest.approx(3.0)


def test_effective_interval_stretch_is_capped(monkeypatch):
    # The live incident: load ~80 on a laptop. Stretch must cap, not explode.
    monkeypatch.setattr(os, "getloadavg", lambda: (80.0, 80.0, 80.0))
    monkeypatch.setattr(os, "cpu_count", lambda: 8)
    assert _d._effective_interval(1.0) == _d.INTERVAL_STRETCH_MAX


def test_effective_interval_survives_platforms_without_loadavg(monkeypatch):
    def _raise():
        raise OSError("no loadavg here")
    monkeypatch.setattr(os, "getloadavg", _raise)
    assert _d._effective_interval(1.0) == 1.0


# ---------------------------------------------------------------------------
# 3. Circuit breaker + fairness ordering
# ---------------------------------------------------------------------------
def _run_batch(monkeypatch, sids, durations, clock):
    """Run one _render_all_sessions batch with a fake clock. `durations`
    maps sid -> seconds its render pretends to take."""
    monkeypatch.setattr(_d, "_active_sessions", lambda: list(sids))
    order = []

    def fake_render(sid, stale_after=_d.META_STALE_AFTER):
        order.append(sid)
        clock["now"] += durations.get(sid, 0.01)
        return True

    monkeypatch.setattr(_d, "_render_session", fake_render)
    monkeypatch.setattr(_d.time, "time", lambda: clock["now"])
    n = _d._render_all_sessions(1.0)
    return n, order


def test_slow_session_is_backed_off(monkeypatch):
    clock = {"now": 1000.0}
    sids = ["fast-1", "slow-x", "fast-2"]
    durations = {"slow-x": _d.SLOW_RENDER_S + 1.0}

    n, order = _run_batch(monkeypatch, sids, durations, clock)
    assert n == 3
    assert "slow-x" in _d._skip_until, "slow session must enter the breaker"
    assert "fast-1" not in _d._skip_until
    assert "fast-2" not in _d._skip_until

    # Next batch (1s later): the slow session is skipped, the fast ones render.
    clock["now"] += 1.0
    n2, order2 = _run_batch(monkeypatch, sids, durations, clock)
    assert "slow-x" not in order2, "breaker must skip the slow session"
    assert set(order2) == {"fast-1", "fast-2"}


def test_breaker_backoff_grows_and_recovers(monkeypatch):
    clock = {"now": 2000.0}
    durations = {"sick": _d.SLOW_RENDER_S + 1.0}

    _run_batch(monkeypatch, ["sick"], durations, clock)
    first_penalty = _d._skip_until["sick"] - clock["now"]

    # Wait out the penalty; it renders slow again → penalty doubles.
    clock["now"] = _d._skip_until["sick"] + 0.1
    _run_batch(monkeypatch, ["sick"], durations, clock)
    second_penalty = _d._skip_until["sick"] - clock["now"]
    assert second_penalty > first_penalty

    # A healthy render clears the breaker entirely.
    clock["now"] = _d._skip_until["sick"] + 0.1
    _run_batch(monkeypatch, ["sick"], {}, clock)
    assert "sick" not in _d._skip_until
    assert "sick" not in _d._slow_streak


def test_fast_sessions_render_before_slow_ones(monkeypatch):
    clock = {"now": 3000.0}
    monkeypatch.setattr(_d, "_render_ema", {"tortoise": 4.0, "hare": 0.02})
    n, order = _run_batch(monkeypatch, ["tortoise", "hare"], {}, clock)
    assert order == ["hare", "tortoise"], (
        "EMA-fast sessions must render first so a slow tail can't age them"
    )


def test_unrelated_sessions_stay_within_advertised_window(monkeypatch, tmp_path):
    """Issue #49 acceptance: one session at the per-render timeout must not
    make unrelated sessions stale. End-to-end through real _render_session:
    the batch's advertised stale_after covers the slow tail, so every meta
    written in the batch stays fresh by its own window."""
    monkeypatch.setenv("HOME", str(tmp_path))
    sids = ["ok-a", "ok-b", "slow-c", "ok-d"]
    for sid in sids:
        _d.session_stdin_path(sid).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(_d, "_active_sessions", lambda: list(sids))
    # Previous batch was slow (the slow session hit the 12s cap).
    monkeypatch.setattr(_d, "_last_batch_s", 12.0)
    monkeypatch.setattr(_d, "_render_payload", lambda payload: "BAR")

    _d._render_all_sessions(1.0)

    for sid in sids:
        meta = json.loads(_d.session_meta_path(sid).read_text(encoding="utf-8"))
        age = time.time() - meta["generated_at"]
        assert age <= meta["stale_after_seconds"], (
            f"{sid} rendered this batch but is already stale by its own meta"
        )
        assert meta["stale_after_seconds"] == pytest.approx(26.0)  # 2*(12+1)


# ---------------------------------------------------------------------------
# 4. Thin client: stale-while-revalidate + inline slot cap
# ---------------------------------------------------------------------------
def test_swr_serves_stale_output_instead_of_inline(monkeypatch, tmp_path, capsys):
    """Meta 10s old with a 5s window: within grace → serve the last render
    (marked ⟳), nudge the daemon, and never touch the inline path."""
    _setup_session_paths(monkeypatch, tmp_path)
    sid = "swr-sid"
    _write_session(tmp_path, sid, age=10.0, stale_after=5.0)
    payload = json.dumps({"session_id": sid}).encode()
    monkeypatch.setattr(render_thin, "_consume_stdin", lambda: payload)

    spawned = []
    monkeypatch.setattr(render_thin, "_spawn_daemon_async",
                        lambda: spawned.append(True))

    def _fail_inline():
        raise AssertionError("inline render must not run inside the SWR grace window")
    monkeypatch.setattr(render_thin, "_fallback_inline", _fail_inline)

    assert render_thin.render() == 0
    out = capsys.readouterr().out
    assert "LAST GOOD BAR" in out
    assert "⟳" in out, "stale-served output must carry the catching-up mark"
    assert spawned == [True], "SWR must still nudge the daemon"


def test_swr_respects_adaptive_window(monkeypatch, tmp_path, capsys):
    """A meta advertising a 26s window is not even stale at 10s — fast path,
    no ⟳ mark."""
    _setup_session_paths(monkeypatch, tmp_path)
    sid = "wide-sid"
    _write_session(tmp_path, sid, age=10.0, stale_after=26.0)
    payload = json.dumps({"session_id": sid}).encode()
    monkeypatch.setattr(render_thin, "_consume_stdin", lambda: payload)

    assert render_thin.render() == 0
    out = capsys.readouterr().out
    assert "LAST GOOD BAR" in out
    assert "⟳" not in out


def test_beyond_grace_goes_inline(monkeypatch, tmp_path):
    """Output older than stale_after + grace is genuinely dead — inline."""
    _setup_session_paths(monkeypatch, tmp_path)
    sid = "dead-sid"
    _write_session(tmp_path, sid, age=5.0 + render_thin._SWR_GRACE_S + 10.0)
    payload = json.dumps({"session_id": sid}).encode()
    monkeypatch.setattr(render_thin, "_consume_stdin", lambda: payload)
    monkeypatch.setattr(render_thin, "_spawn_daemon_async", lambda: None)

    inlined = []
    monkeypatch.setattr(render_thin, "_fallback_inline",
                        lambda: (inlined.append(True), 0)[1])
    assert render_thin.render() == 0
    assert inlined == [True]


def test_future_timestamp_skips_swr(monkeypatch):
    """Clock-skew defense carries over: a future generated_at must not be
    served as 'recent enough'."""
    assert render_thin._swr_ok(
        {"generated_at": time.time() + 60.0, "stale_after_seconds": 5.0}
    ) is False


def test_inline_slots_are_bounded(monkeypatch, tmp_path):
    """At most _INLINE_SLOTS flocks can be held machine-wide."""
    fcntl = pytest.importorskip("fcntl")
    monkeypatch.setattr(render_thin, "_CACHE_DIR", tmp_path)

    # Simulate other cs render processes holding every slot.
    holders = []
    for i in range(render_thin._INLINE_SLOTS):
        fh = open(tmp_path / f"inline.slot.{i}", "a+b")
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        holders.append(fh)

    assert render_thin._acquire_inline_slot() is False

    # One holder exits → a slot frees up.
    fcntl.flock(holders[0].fileno(), fcntl.LOCK_UN)
    holders[0].close()
    assert render_thin._acquire_inline_slot() is True

    for fh in holders[1:]:
        fh.close()


def test_over_cap_client_serves_stale_instead_of_piling_on(monkeypatch, tmp_path, capsys):
    """The herd killer: with every inline slot taken, a client must serve
    the last render at ANY age rather than start another heavy render."""
    _setup_session_paths(monkeypatch, tmp_path)
    sid = "shed-sid"
    _write_session(tmp_path, sid, age=500.0)  # ancient — way past grace
    monkeypatch.setattr(render_thin, "_acquire_inline_slot", lambda: False)

    def _fail_inline():
        raise AssertionError("over-cap client must not join the herd")
    monkeypatch.setattr(render_thin, "_fallback_inline", _fail_inline)

    _, rendered_path, _ = render_thin._session_paths(sid)
    assert render_thin._inline_or_shed(None, rendered_path) == 0
    out = capsys.readouterr().out
    assert "LAST GOOD BAR" in out
    assert "⟳" in out


def test_over_cap_client_with_no_cache_still_renders(monkeypatch, tmp_path):
    """First run on a machine (no cached render anywhere): correctness beats
    the cap — render inline even when slots are exhausted."""
    monkeypatch.setattr(render_thin, "_CACHE_DIR", tmp_path)
    monkeypatch.setattr(render_thin, "_acquire_inline_slot", lambda: False)
    inlined = []
    monkeypatch.setattr(render_thin, "_fallback_inline",
                        lambda: (inlined.append(True), 0)[1])
    assert render_thin._inline_or_shed(None, tmp_path / "nope.ansi") == 0
    assert inlined == [True]


def test_swr_ok_defaults_legacy_meta_window(monkeypatch):
    """Metas written by a pre-3.41 daemon lack nothing (they always had
    stale_after_seconds), but be safe about a missing field anyway."""
    assert render_thin._swr_ok({"generated_at": time.time() - 10.0}) is True
    assert render_thin._swr_ok({"generated_at": "bogus"}) is False
