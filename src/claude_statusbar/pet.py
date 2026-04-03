"""ASCII pet system for the status bar."""

import hashlib
import random
import time
from typing import Optional

# Pet names pool
PET_NAMES = [
    "Mochi", "Neko", "Pixel", "Byte", "Chip", "Tux", "Null", "Bit",
    "Tofu", "Ping", "Dash", "Flux", "Giga", "Nano", "Zap", "Boop",
    "Fizz", "Watt", "Hex", "Pico",
]

# Cat face frames per mood level (for blink animation)
# Each mood has 2-3 frames; frame selection uses time-based tick
CAT_FACES = {
    "chill":   ["ᓚᘏᗢ", "ᓚᘏ-ᗢ", "ᓚᘏᗢ"],
    "sleepy":  ["ᓚᘏ-.", "ᓚᘏ_.", "ᓚᘏ-."],
    "working": ["ᓚᘏᗢ", "ᓚᘏ-ᗢ", "ᓚᘏᗢ"],
    "nervous": ["ᓚᘏᗢ;", "ᓚᘏ-ᗢ;", "ᓚᘏᗢ;"],
    "panic":   ["ᓚᘏᗢ!", "ᓚᘏᗢ!", "ᓚᘏ⊙ᗢ!"],
    "hype":    ["ᓚ₍ᘏ₎ᗢ", "ᓚ₍ᘏ₎ᗢ!", "ᓚ₍ᘏ₎ᗢ"],
}

# Status text pools per mood
STATUS_TEXTS = {
    "chill":   ["chilling~", "vibing~", "relaxed~", "all good~", "easy~"],
    "sleepy":  ["zzz...", "sleepy...", "nap time...", "*yawn*", "dozing..."],
    "working": ["working!", "coding~", "focused!", "busy~", "on it!"],
    "nervous": ["hmm...", "uh oh...", "getting warm...", "careful...", "watch out..."],
    "panic":   ["help!!", "oh no!!", "critical!!", "mayday!!", "SOS!!"],
    "hype":    ["almost there!", "reset hype!!", "HERE IT COMES!", "so close!", "any moment!"],
    "refreshed": ["refreshed~", "brand new!", "recharged!", "lets go!", "reset!"],
}


def get_pet_name(session_id: str = "", custom_name: Optional[str] = None) -> str:
    """Pick a pet name. Custom name wins, otherwise deterministic random from session_id."""
    if custom_name:
        return custom_name
    if session_id:
        seed = int(hashlib.md5(session_id.encode()).hexdigest()[:8], 16)
    else:
        seed = 42
    rng = random.Random(seed)
    return rng.choice(PET_NAMES)


def _get_mood(pct: float, hour: int, minutes_to_reset: Optional[int] = None) -> str:
    """Determine pet mood from usage percentage, time of day, and reset proximity."""
    # Reset hype overrides everything when usage is high
    if minutes_to_reset is not None and minutes_to_reset <= 30 and pct >= 50:
        return "hype"

    # Just reset — low usage after being high
    if pct <= 5:
        return "refreshed" if minutes_to_reset and minutes_to_reset > 280 else "chill"

    # Night time override for low usage
    if pct <= 20 and (hour >= 23 or hour < 6):
        return "sleepy"

    # Usage-based mood
    if pct <= 20:
        return "chill"
    if pct <= 50:
        return "working"
    if pct <= 70:
        return "nervous"
    return "panic"


def _get_frame_tick() -> int:
    """Get a frame index based on current time (changes every ~3 seconds)."""
    return int(time.time() / 3) % 3


def get_pet_face(mood: str) -> str:
    """Get the cat face for current mood with blink animation."""
    face_key = mood if mood in CAT_FACES else "chill"
    frames = CAT_FACES[face_key]
    tick = _get_frame_tick()
    return frames[tick % len(frames)]


def get_pet_status(mood: str, session_id: str = "") -> str:
    """Pick a status text for the mood. Varies per refresh but stable within ~5s windows."""
    texts = STATUS_TEXTS.get(mood, STATUS_TEXTS["chill"])
    # Use time window + session_id for variety that's stable for a few seconds
    window = int(time.time() / 5)
    if session_id:
        seed = hash((window, session_id))
    else:
        seed = window
    rng = random.Random(seed)
    return rng.choice(texts)


def format_pet(
    pct: float,
    hour: int,
    session_id: str = "",
    minutes_to_reset: Optional[int] = None,
    custom_name: Optional[str] = None,
) -> str:
    """Build the full pet string for the status bar.

    Example: "ᓚᘏᗢ Pixel:working!"
    """
    name = get_pet_name(session_id, custom_name)
    mood = _get_mood(pct, hour, minutes_to_reset)
    face = get_pet_face(mood)
    status = get_pet_status(mood, session_id)
    return f"{face} {name}:{status}"


def get_countdown_emoji(minutes_to_reset: Optional[int]) -> str:
    """Get countdown emoji based on proximity to reset.

    Returns empty string when not in countdown range.
    """
    if minutes_to_reset is None:
        return ""
    if minutes_to_reset <= 1:
        return " \U0001f389"  # party popper
    if minutes_to_reset <= 10:
        return " \u2728"  # sparkles
    if minutes_to_reset <= 30:
        return " \u26a1"  # lightning
    return ""
