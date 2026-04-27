"""Multi-track pet animation tests.

The point of multi-track animation is that two consecutive renders, even
~50ms apart, look different. We assert that on a typical "active typing"
sample window we see multiple distinct frames.
"""

import pytest

from claude_statusbar import pet_animation as anim


# ---------------------------------------------------------------------------
# Per-track determinism + period
# ---------------------------------------------------------------------------
def test_tail_4_frame_cycle_at_250ms():
    """One full cycle = 1 second across all 4 frames."""
    seen = {anim.tail_frame(t * 0.25) for t in range(4)}
    assert seen == set(anim.TAIL_FRAMES)


def test_aura_cycles_through_full_palette():
    pal = anim.AURA_HYPE
    seen = {anim.aura_frame(i * 0.2, pal) for i in range(len(pal))}
    assert seen == set(pal)


def test_aura_empty_palette():
    assert anim.aura_frame(123.45, ()) == ""


def test_breath_phase_alternates_every_700ms():
    assert anim.breath_phase(0.0) == 0
    assert anim.breath_phase(0.69) == 0
    assert anim.breath_phase(0.71) == 1
    assert anim.breath_phase(1.41) == 0


# ---------------------------------------------------------------------------
# Random tracks must be deterministic across processes (no hash() salt)
# ---------------------------------------------------------------------------
def test_blink_deterministic_for_same_seed():
    a = [anim.is_blinking(t * 0.08, "x") for t in range(50)]
    b = [anim.is_blinking(t * 0.08, "x") for t in range(50)]
    assert a == b


def test_blink_differs_by_session_seed():
    a = sum(anim.is_blinking(t * 0.08, "alice") for t in range(500))
    b = sum(anim.is_blinking(t * 0.08, "bob")   for t in range(500))
    # Both should be roughly 3% of 500 ≈ 15. Different seeds → different
    # exact counts. Probability of equality is tiny.
    # We require the SETS of blink times differ.
    set_a = {t for t in range(500) if anim.is_blinking(t * 0.08, "alice")}
    set_b = {t for t in range(500) if anim.is_blinking(t * 0.08, "bob")}
    assert set_a != set_b


def test_blink_stable_within_window():
    """Two renders inside the same ~80ms window agree."""
    t1 = 1000.000
    t2 = 1000.030  # 30ms later, same window
    assert anim.is_blinking(t1, "x") == anim.is_blinking(t2, "x")


def test_blink_rate_roughly_3_percent():
    """Sample 1000 windows; rate should land in [1%, 6%]."""
    n = 1000
    hits = sum(anim.is_blinking(t / anim._BLINK_WINDOWS_PER_SEC, "rate") for t in range(n))
    assert 10 <= hits <= 60, f"blink rate looks off: {hits}/{n}"


def test_ear_twitch_rare():
    """~1% per ~150ms window. Sample 2000 windows."""
    hits = sum(anim.is_ear_twitching(t / anim._EAR_WINDOWS_PER_SEC, "ear") for t in range(2000))
    assert 5 <= hits <= 60


# ---------------------------------------------------------------------------
# compose_face — the main reason this exists
# ---------------------------------------------------------------------------
def test_compose_face_changes_during_active_typing():
    """At 5Hz redraw rate, we should see at least 3 distinct frames per second."""
    seen = set()
    for i in range(10):  # 10 renders × 100ms = 1s
        seen.add(anim.compose_face("chill", i * 0.1, "sess"))
    assert len(seen) >= 3, f"animation looked too static: {seen!r}"


def test_compose_face_changes_in_hype_mode():
    """Hype has aura particles that cycle independently from tail."""
    seen = set()
    for i in range(10):
        seen.add(anim.compose_face("hype", i * 0.1, "sess"))
    assert len(seen) >= 5, f"hype should be most lively: {seen!r}"


def test_compose_face_panic_alternates():
    """Lightning flashes on/off."""
    a = anim.compose_face("panic", 0.0, "x")
    b = anim.compose_face("panic", 0.2, "x")
    assert a != b


def test_compose_face_sleepy_z_count_varies():
    """Z trail count cycles."""
    seen = {anim.compose_face("sleepy", i * 0.5, "x") for i in range(8)}
    # Multiple distinct Z-counts visible in a 4s window
    assert len(seen) >= 2


def test_compose_face_no_tail_when_sleepy_or_panic():
    sleepy = anim.compose_face("sleepy", 0.0, "x")
    assert "⌒" not in sleepy and "∽" not in sleepy
    panic = anim.compose_face("panic", 0.0, "x")
    assert "⌒" not in panic and "∽" not in panic


def test_compose_face_unknown_mood_falls_back_to_chill():
    out = anim.compose_face("not-a-real-mood", 0.0, "x")
    # Default eye, has tail = chill-like
    assert "ᘏ" in out or "ᗢ" in out


def test_compose_face_blink_hides_eyes():
    """Find a frame where blink fires and assert eye is closed."""
    for i in range(500):
        t = i * 0.08
        if anim.is_blinking(t, "x"):
            face = anim.compose_face("chill", t, "x")
            assert "-" in face, f"blink should close eyes, got {face!r}"
            return
    pytest.skip("no blink hit in sample window")


# ---------------------------------------------------------------------------
# Perf budget — the animation engine sits in the statusLine hot path; if a
# regression slows it past a few microseconds per call, every keystroke the
# user types pays the cost. We keep a generous 50 µs ceiling.
# ---------------------------------------------------------------------------
def test_compose_face_microbench_under_budget():
    import time as _time
    iters = 5000
    t0 = _time.perf_counter()
    for i in range(iters):
        anim.compose_face("chill", t0 + i * 0.05, "sess")
    elapsed_us_per_call = (_time.perf_counter() - t0) / iters * 1e6
    assert elapsed_us_per_call < 50, (
        f"compose_face is now {elapsed_us_per_call:.1f} µs/call — "
        f"animation hot path is slow"
    )
