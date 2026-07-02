# An official downward re-baseline must actually land on the bar.
#
# Live incident 2026-07-02 (Claude 5 launch): Anthropic re-baselined the
# weekly window mid-cycle (seven_day 63% → 2%, same resets_at). The bar held
# 63% indefinitely because of two composing bugs:
#
# 1. Echo-confirmation: core.main reconciles the raw blob (2% loses to the
#    stored 63% within grace), then feeds the RECONCILED 63% into
#    projection()/forecast(), whose internal reconcile_account calls hit the
#    equal-confirm branch and restart the DOWNGRADE_GRACE_S clock — every
#    render by ANY session (even one reading 2%) re-confirmed 63%, so the
#    store could never become unconfirmed. Fix: derived calls pass
#    record=False and never write or confirm.
#
# 2. Idle replay: idle-but-open sessions replay a frozen pre-re-baseline blob
#    (7d=63%) whose five_hour resets_at is still inside the current window,
#    so the blob-freshness gate can't date it. Fix: track each session's
#    rate-limits signature; a session whose signature hasn't changed for
#    RL_IDLE_TTL_S is replaying a frozen blob and loses write/confirm rights
#    (display still answered from the shared store).
import json

import claude_statusbar.predict as predict
from claude_statusbar.predict import forecast, projection, reconcile_account


NOW = 1_782_900_000.0
R5 = NOW + 3 * 3600          # five_hour reset, plausible throughout the test
R7 = NOW + 3 * 86400         # seven_day reset, shared by old and new readings


def _store(tmp_path):
    return json.loads((tmp_path / "rate_latest.json").read_text())


# --- bug 1: derived (echo) reconciles must not write or confirm ---

def test_record_false_never_writes(tmp_path):
    reconcile_account(10.0, R5, 63.0, R7, now=NOW)
    before = _store(tmp_path)
    # higher, equal and new-window readings — none may touch the store
    reconcile_account(11.0, R5, 64.0, R7, now=NOW + 30, record=False)
    reconcile_account(10.0, R5, 63.0, R7, now=NOW + 30, record=False)
    reconcile_account(10.0, R5 + 18000, 63.0, R7, now=NOW + 30, record=False)
    assert _store(tmp_path) == before


def test_echo_confirmation_does_not_extend_grace(tmp_path):
    """The live loop: render reconciles raw 2% (loses in grace), then feeds
    the returned 63% to forecast()/projection(). Those echoes must not
    restart the grace clock, so the next raw 2% after grace expiry wins."""
    reconcile_account(10.0, R5, 63.0, R7, now=NOW)
    grace = predict.DOWNGRADE_GRACE_S
    step = 20.0
    t = NOW
    while t < NOW + grace + 3 * step:
        t += step
        u5, r5, u7, r7 = reconcile_account(10.0, R5, 2.0, R7, now=t)
        # what core.main does with the reconciled values every render:
        forecast(u5, r5, u7, r7, now=t)
        projection(u5, r5, u7, r7, now=t, session_id="sess-a")
    assert u7 == 2.0


# --- bug 2: frozen idle-session replays lose confirm rights after TTL ---

def _replay(sid, u7, t, u5=10.0):
    return reconcile_account(u5, R5, u7, R7, now=t, session_id=sid)


def test_frozen_replay_stops_confirming_after_ttl(tmp_path):
    """Idle session A replays a frozen 63% blob forever; active session B's
    signature keeps changing and reads 2%. Once A's signature has been
    frozen past RL_IDLE_TTL_S, its replays no longer refresh the grace
    clock, and B's re-baseline lands."""
    ttl = predict.RL_IDLE_TTL_S
    grace = predict.DOWNGRADE_GRACE_S
    _replay("idle-a", 63.0, NOW)
    t = NOW
    u7 = None
    while t < NOW + ttl + grace + 120.0:
        t += 30.0
        _replay("idle-a", 63.0, t)                       # frozen signature
        u5 = 10.0 + (t - NOW) / 600.0                    # B's usage creeps up
        _, _, u7, _ = reconcile_account(u5, R5, 2.0, R7,
                                        now=t, session_id="active-b")
    assert u7 == 2.0


def test_frozen_replay_cannot_reupgrade_after_heal(tmp_path):
    """After the 2% lands, the frozen session still replays 63% (> 2%): the
    monotonic-up rule must not resurrect it, and the frozen session's own
    render shows the shared 2%."""
    ttl = predict.RL_IDLE_TTL_S
    grace = predict.DOWNGRADE_GRACE_S
    _replay("idle-a", 63.0, NOW)
    healed_at = NOW + ttl + grace + 60.0
    _, _, u7, _ = reconcile_account(11.0, R5, 2.0, R7,
                                    now=healed_at, session_id="active-b")
    assert u7 == 2.0
    _, _, u7_idle, _ = _replay("idle-a", 63.0, healed_at + 15.0)
    assert u7_idle == 2.0
    assert _store(tmp_path)["seven_day"][str(int(R7))]["used"] == 2.0


def test_changing_session_keeps_glitch_protection(tmp_path):
    """A session whose signature changes stays trusted: within grace a lower
    reading from another session still loses (v3.13 behaviour intact)."""
    _replay("live-a", 63.0, NOW, u5=10.0)
    _replay("live-a", 63.0, NOW + 60.0, u5=11.0)         # signature changed
    _, _, u7, _ = reconcile_account(11.0, R5, 3.0, R7,
                                    now=NOW + 90.0, session_id="live-b")
    assert u7 == 63.0


def test_session_sig_entries_are_bounded(tmp_path):
    for i in range(predict.MAX_SESSION_SIGS + 10):
        reconcile_account(10.0 + i, R5, 5.0, R7, now=NOW + i,
                          session_id=f"sess-{i}")
    sess = _store(tmp_path).get("sessions", {})
    assert len(sess) <= predict.MAX_SESSION_SIGS


def test_no_session_id_behaves_as_before(tmp_path):
    reconcile_account(10.0, R5, 63.0, R7, now=NOW)
    _, _, u7, _ = reconcile_account(10.0, R5, 2.0, R7, now=NOW + 30.0)
    assert u7 == 63.0                                    # in-grace drop loses
    _, _, u7, _ = reconcile_account(
        10.0, R5, 2.0, R7, now=NOW + predict.DOWNGRADE_GRACE_S + 31.0)
    assert u7 == 2.0                                     # heals after grace
