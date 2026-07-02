# Burn-rate regime detection (v3.19.0): a model switch or a novel-model
# session joining the fleet marks a regime boundary; rate estimation must not
# average across it, so →NN% jumps onto the new burn rate within minutes
# instead of dragging the old regime's rate for 30-60 min.
# Design: docs/superpowers/specs/2026-07-02-burn-regime-detection-design.html
import json

import claude_statusbar.predict as predict
from claude_statusbar.predict import (
    reconcile_account, regime_changed_at, _rate_from_samples, project_5h,
)


NOW = 1_782_900_000.0
R5 = NOW + 3 * 3600
R7 = NOW + 3 * 86400


def _rec(sid, t, model, u5=10.0):
    return reconcile_account(u5, R5, 5.0, R7, now=t,
                             session_id=sid, model=model)


def _store(tmp_path):
    return json.loads((tmp_path / "rate_latest.json").read_text())


# --- detection in reconcile_account ---

def test_model_switch_bumps_regime(tmp_path):
    _rec("s1", NOW, "claude-sonnet-5")
    assert regime_changed_at() is None          # first sighting: no history to clip
    _rec("s1", NOW + 60, "claude-fable-5", u5=11.0)
    assert regime_changed_at() == NOW + 60
    assert _store(tmp_path)["regime"]["reason"] == "model-switch"


def test_same_model_never_bumps(tmp_path):
    _rec("s1", NOW, "claude-sonnet-5")
    _rec("s1", NOW + 60, "claude-sonnet-5", u5=11.0)
    assert regime_changed_at() is None


def test_novel_model_join_bumps(tmp_path):
    _rec("s1", NOW, "claude-sonnet-5")
    _rec("s2", NOW + 60, "claude-fable-5", u5=11.0)   # new session, new model
    assert regime_changed_at() == NOW + 60
    assert _store(tmp_path)["regime"]["reason"] == "fleet-join"


def test_same_model_join_does_not_bump(tmp_path):
    _rec("s1", NOW, "claude-sonnet-5")
    _rec("s2", NOW + 60, "claude-sonnet-5", u5=11.0)
    assert regime_changed_at() is None


def test_missing_model_and_echo_never_bump(tmp_path):
    _rec("s1", NOW, "claude-sonnet-5")
    _rec("s1", NOW + 60, None, u5=11.0)               # model missing: keep old
    reconcile_account(12.0, R5, 5.0, R7, now=NOW + 90,
                      session_id="s1", model="claude-fable-5", record=False)
    assert regime_changed_at() is None
    # the stored model survived the None update
    assert _store(tmp_path)["sessions"]["s1"]["model"] == "claude-sonnet-5"


def test_stale_fleet_entry_is_not_fleet(tmp_path):
    """A session idle past FLEET_ACTIVE_S no longer defines the fleet: a new
    session with that same model still counts as a novel joiner? No — the
    other way: sonnet went idle long ago, fable is the fleet now, and a NEW
    sonnet session is novel again."""
    _rec("s1", NOW, "claude-sonnet-5")
    _rec("s2", NOW + 10, "claude-fable-5", u5=11.0)   # bump 1 (novel fable)
    t = NOW + predict.FLEET_ACTIVE_S + 600
    _rec("s2", t, "claude-fable-5", u5=12.0)          # keep fable fresh
    _rec("s3", t + 30, "claude-sonnet-5", u5=13.0)    # sonnet is stale → novel
    assert regime_changed_at() == t + 30


# --- rate estimation clipping ---

def _samples(rows):
    return [{"observed_at": t, "used_pct": u, "resets_at": R5} for t, u in rows]


def test_rate_clips_to_regime_boundary():
    # old regime: 20%/h for 30 min; boundary; new regime: 2%/h for 10 min
    boundary = NOW - 600
    s = _samples([(NOW - 3600 + k * 300, 10.0 + k * (20 / 12)) for k in range(10)]
                 + [(boundary + 120, 26.0), (boundary + 600, 26.3)])
    unclipped = _rate_from_samples(s, NOW, 3600.0, window="five_hour")
    clipped = _rate_from_samples(s, NOW, 3600.0, window="five_hour",
                                 since=boundary)
    assert clipped is not None and unclipped is not None
    assert clipped < unclipped / 3                    # new slow regime only


def test_rate_relaxes_span_after_boundary():
    # only 150s of post-boundary data: < MIN_RECENT_RATE_SPAN_S (300) but
    # >= REGIME_MIN_SPAN_S (120) — must yield a rate instead of None
    boundary = NOW - 200
    s = _samples([(boundary + 20, 10.0), (boundary + 170, 11.0)])
    assert _rate_from_samples(s, NOW, 3600.0, window="five_hour") is None
    r = _rate_from_samples(s, NOW, 3600.0, window="five_hour", since=boundary)
    assert r is not None and r > 0


def test_project_5h_jumps_onto_new_regime():
    """Sonnet era burned 2%/h for 50 min; switch to Fable, 24%/h for 10 min.
    With the boundary the projection must be driven by the fast era."""
    boundary = NOW - 600
    slow = [(NOW - 3600 + k * 300, 10.0 + k * 0.17) for k in range(10)]
    fast = [(boundary + 150, 13.0), (boundary + 400, 14.5), (boundary + 590, 16.0)]
    s = _samples(slow + fast)
    used = 16.0
    p_old = project_5h(used, R5, NOW, s)
    p_new = project_5h(used, R5, NOW, s, since=boundary)
    assert p_new > p_old + 5                          # jumps, not averages


def test_project_5h_since_none_is_v318_behavior():
    s = _samples([(NOW - 1200 + k * 300, 10.0 + k) for k in range(5)])
    assert project_5h(12.0, R5, NOW, s) == project_5h(12.0, R5, NOW, s, since=None)


# --- display smoothing reset ---

def test_projection_display_resets_at_regime_boundary(tmp_path, monkeypatch):
    monkeypatch.setattr(predict, "_PROJECTION_PATH", tmp_path / "proj.json")
    monkeypatch.setattr(predict, "_PROJECTION_RESULT_CACHE", {})
    # seed store + slow-regime display state
    reconcile_account(10.0, R5, 5.0, R7, now=NOW, session_id="s1",
                      model="claude-sonnet-5")
    predict.projection(10.0, R5, 5.0, R7, NOW, session_id="s1")
    st = predict.load_projection_store()
    st["five_hour"] = _samples([(NOW - 900, 8.0), (NOW - 450, 9.0), (NOW, 10.0)])
    predict.save_projection_store(st)
    before = predict.projection(10.0, R5, 5.0, R7, NOW + 30, session_id="s1")[0]
    # regime bump + a fast burst right after the boundary
    monkeypatch.setattr(predict, "_PROJECTION_RESULT_CACHE", {})
    _rec("s1", NOW + 60, "claude-fable-5", u5=11.0)
    st = predict.load_projection_store()
    # ~33%/h post-boundary burst — under the 60%/h cap so the relaxed-span
    # regime rate (not just the avg fallback) drives the jump
    st["five_hour"] += _samples([(NOW + 90, 13.0), (NOW + 240, 14.4)])
    predict.save_projection_store(st)
    after = predict.projection(14.4, R5, 5.0, R7, NOW + 250, session_id="s1")[0]
    # display must jump with the new regime instead of easing over from before
    assert int(after.lstrip("→").rstrip("%")) > int(before.lstrip("→").rstrip("%")) + 10


# --- core.main wiring (regression: model.id is flattened to stdin_data
# ['model_id'] by parse_stdin_data; reading the wrong key made every render
# pass model=None and regime detection never fired in production) ---

def _main_payload(model_id, now):
    return json.dumps({
        "session_id": "wire-1",
        "transcript_path": "/n.jsonl",
        "model": {"id": model_id, "display_name": model_id},
        "rate_limits": {
            "five_hour": {"used_percentage": 12, "resets_at": now + 3600},
            "seven_day": {"used_percentage": 5, "resets_at": now + 3 * 86400},
        },
        "context_window": {"used_percentage": 35,
                           "context_window_size": 1000000,
                           "total_input_tokens": 350000},
    })


def test_core_main_passes_model_into_regime_detection(tmp_path, monkeypatch, capsys):
    import io, sys, time
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("CS_API_MODE", raising=False)
    (tmp_path / ".claude").mkdir(parents=True)
    cfg = tmp_path / ".claude" / "claude-statusbar.json"
    cfg.write_text(json.dumps({"show_project_branch": False, "show_cache_age": False,
                               "show_todos": False, "show_mode": False}))
    import claude_statusbar.config as config
    monkeypatch.setattr(config, "CONFIG_PATH", cfg)
    from claude_statusbar.core import main
    now = time.time()
    for model in ("claude-sonnet-5", "claude-fable-5"):
        monkeypatch.setattr(sys, "stdin", io.StringIO(_main_payload(model, now)))
        main(use_color=False, _suppress_side_effects=True)
    store = json.loads((tmp_path / "rate_latest.json").read_text())
    assert store["sessions"]["wire-1"]["model"] == "claude-fable-5"
    assert store["regime"]["reason"] == "model-switch"
