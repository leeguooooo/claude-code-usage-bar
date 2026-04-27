"""Multi-track time-driven pet animation.

Why this exists
---------------
The pet used to look like a stop-motion puppet: 3 hand-written frames per
mood, swapped every 3 seconds. Boring.

A real pet always seems to move — tail twitching at one rhythm, breathing at
another, eyes blinking randomly, particles drifting. We can't get a true
fixed-rate animation loop because Claude Code only re-invokes the statusLine
on its own events (keystrokes, tool calls, model tokens), but we CAN make
every render be a new frame:

    Each track is a pure function of `time.time()`.

Tracks have *different periods* (tail 250ms, aura 200ms, blink window 80ms,
ear twitch 150ms, breath 700ms). At any wall-clock moment two tracks are at
two different phases — so two consecutive renders, even ~50ms apart, will
show *different* combinations. The pet looks alive whenever the user is
active enough to trigger redraws.

Determinism
-----------
Random tracks (blink, ear twitch) use a deterministic hash of (time-window,
session_id) so all renders within the same ~80ms window agree. We use
`hashlib.md5` because Python's built-in `hash()` is salted per-process via
PYTHONHASHSEED — across cs invocations, two renders in the same window
would otherwise disagree and produce visible flicker.

Adding a new track
------------------
1. Define `def my_frame(t: float, ...) -> str | bool | int`.
2. Wire it into `compose_face()` below.
3. Keep periods coprime-ish so visible cycles don't lock-step.
"""

from __future__ import annotations

import hashlib
from typing import Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _det_unit(seed: str) -> float:
    """Deterministic float in [0, 1). Stable across processes for same seed."""
    return int(hashlib.md5(seed.encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF


# ---------------------------------------------------------------------------
# TRACK: tail — multiple wag styles
# ---------------------------------------------------------------------------
# Smooth happy wag — 4 frames at 250ms (4Hz). Used for chill / working / hype.
TAIL_FRAMES = ("⌒", "~", "∽", "~")

# Short jittery flick — for nervous moods. Real nervous cats twitch the tail
# in shorter bursts than they wag it. 6 frames at 8Hz, with held positions
# to read as agitation rather than relaxed swing.
TAIL_FLICK_FRAMES = (",", "_", ",", "˒", "_", "˒")


def tail_frame(t: float) -> str:
    return TAIL_FRAMES[int(t * 4) % len(TAIL_FRAMES)]


def tail_flick_frame(t: float) -> str:
    return TAIL_FLICK_FRAMES[int(t * 8) % len(TAIL_FLICK_FRAMES)]


# ---------------------------------------------------------------------------
# TRACK: aura particles — mood-dependent palettes, 200ms (5Hz)
# ---------------------------------------------------------------------------
# Each tuple is one full cycle. Spaces inserted intentionally to give a sense
# of breathing-in/out particles rather than a constant glyph.
AURA_HYPE      = ("✦", "✧", "✨", "⋆", "*", "·")
AURA_REFRESHED = ("✨", "✦", "✧", "✨", "·", "·")
AURA_PANIC     = ("⚡", " ", "⚡", "  ")
AURA_SLEEPY    = ("ᶻ ", "ᶻ ", "ᶻᶻ", "ᶻᶻ", "ᶻᶻᶻ", "ᶻᶻᶻ")
AURA_NONE: tuple[str, ...] = ()


def aura_frame(t: float, palette: tuple[str, ...]) -> str:
    if not palette:
        return ""
    return palette[int(t * 5) % len(palette)]


# ---------------------------------------------------------------------------
# TRACK: blink — random, ~3% per ~80ms window
# ---------------------------------------------------------------------------
_BLINK_WINDOWS_PER_SEC = 12.5
_BLINK_PROB = 0.03


def is_blinking(t: float, session_id: str = "") -> bool:
    window = int(t * _BLINK_WINDOWS_PER_SEC)
    return _det_unit(f"blink:{window}:{session_id}") < _BLINK_PROB


# ---------------------------------------------------------------------------
# TRACK: ear twitch — random, ~1% per ~150ms window
# ---------------------------------------------------------------------------
_EAR_WINDOWS_PER_SEC = 6.6
_EAR_PROB = 0.01


def is_ear_twitching(t: float, session_id: str = "") -> bool:
    window = int(t * _EAR_WINDOWS_PER_SEC)
    return _det_unit(f"ear:{window}:{session_id}") < _EAR_PROB


# ---------------------------------------------------------------------------
# TRACK: breath — body micro-shift every 700ms
# ---------------------------------------------------------------------------
def breath_phase(t: float) -> int:
    """Returns 0 (in) or 1 (out). Used to shift one element by 1 cell."""
    return int(t / 0.7) % 2


# ---------------------------------------------------------------------------
# Mood → eye glyph
# ---------------------------------------------------------------------------
# The cat body template is `ᓚ{eye}ᗢ`. Eye is the middle char.
EYE_DEFAULT   = "ᘏ"   # dot eyes — calm baseline
EYE_BLINK     = "-"   # closed
EYE_SLEEPY    = "_"   # heavily closed
EYE_PANIC     = "x"
EYE_NERVOUS   = "•"
EYE_HYPE      = "✦"
EYE_REFRESHED = "✦"
EYE_CHILL     = EYE_DEFAULT
EYE_WORKING   = EYE_DEFAULT
EYE_HAPPY     = "^"

_MOOD_EYE = {
    "chill":     EYE_CHILL,
    "working":   EYE_WORKING,
    "nervous":   EYE_NERVOUS,
    "panic":     EYE_PANIC,
    "hype":      EYE_HYPE,
    "refreshed": EYE_REFRESHED,
    "sleepy":    EYE_SLEEPY,
    "studying":  EYE_DEFAULT,
    "leveling":  EYE_HYPE,
}

_MOOD_AURA = {
    "hype":      AURA_HYPE,
    "refreshed": AURA_REFRESHED,
    "panic":     AURA_PANIC,
    "sleepy":    AURA_SLEEPY,
    "leveling":  AURA_HYPE,
}

# Moods where the tail does a relaxed wag.
_MOOD_TAIL_WAGS = {"chill", "working", "hype", "refreshed", "studying", "leveling"}

# Moods where the tail flicks instead of waving — keeps the pet visibly
# alive in 30-70% range (nervous) without misleading the user about its
# emotional state.
_MOOD_TAIL_FLICKS = {"nervous"}


# ---------------------------------------------------------------------------
# Face composer
# ---------------------------------------------------------------------------
def compose_face(
    mood: str,
    t: float,
    session_id: str = "",
) -> str:
    """Render one frame of the cat face.

    Output shape:  [aura_prefix] body [tail] [aura_suffix]
    Examples:
        chill, normal:  ᓚᘏᗢ⌒
        chill, blink:   ᓚ-ᗢ⌒
        chill, ear:     ᓛᘏᗢ⌒
        chill, breath:  ᓚᘏᗢ ⌒   (one space before tail)
        hype:           ✦ᓚ✦ᗢ~
        panic:          ⚡ᓚxᗢ
        sleepy:         ᓚ_ᗢ ᶻᶻ
    """
    # Eye selection: blink overrides everything except sleepy/panic where
    # the closed-eye glyph IS the mood signal (a blink there would be invisible).
    eye = _MOOD_EYE.get(mood, EYE_DEFAULT)
    if is_blinking(t, session_id) and mood not in ("sleepy", "panic"):
        eye = EYE_BLINK

    # Ear: rare twitch swaps left ear glyph.
    left_ear = "ᓛ" if is_ear_twitching(t, session_id) else "ᓚ"

    body = f"{left_ear}{eye}ᗢ"

    # Tail — relaxed wag, jittery flick, or none.
    if mood in _MOOD_TAIL_WAGS:
        tail = tail_frame(t)
    elif mood in _MOOD_TAIL_FLICKS:
        tail = tail_flick_frame(t)
    else:
        tail = ""

    # Breath — insert a single-space "exhale" between body and tail every
    # ~700ms. Subtle but ever-present.
    breath_gap = " " if breath_phase(t) and tail else ""

    # Aura — mood-dependent particle stream.
    aura_palette = _MOOD_AURA.get(mood, AURA_NONE)
    aura = aura_frame(t, aura_palette)

    if mood == "sleepy":
        # Z's drift to the right.
        return f"{body} {aura}".rstrip()
    if mood == "panic":
        # Lightning brackets the body, no tail.
        return f"{aura}{body}".rstrip() if aura.strip() else body
    if mood in ("hype", "refreshed", "leveling") and aura:
        # Sparkle prefix.
        return f"{aura}{body}{breath_gap}{tail}"

    return f"{body}{breath_gap}{tail}"


# Public re-exports for tests
__all__ = (
    "compose_face",
    "tail_frame",
    "aura_frame",
    "is_blinking",
    "is_ear_twitching",
    "breath_phase",
    "AURA_HYPE",
    "AURA_REFRESHED",
    "AURA_PANIC",
    "AURA_SLEEPY",
    "TAIL_FRAMES",
)
