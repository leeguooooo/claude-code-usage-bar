"""ASCII pet system for the status bar."""

import hashlib
import json
import random
import time
from pathlib import Path
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
    "chill":    ["chilling~", "vibing~", "relaxed~", "all good~", "easy~"],
    "sleepy":   ["zzz...", "sleepy...", "nap time...", "*yawn*", "dozing..."],
    "working":  ["working!", "coding~", "focused!", "busy~", "on it!"],
    "nervous":  ["hmm...", "uh oh...", "getting warm...", "careful...", "watch out..."],
    "panic":    ["help!!", "oh no!!", "critical!!", "mayday!!", "SOS!!"],
    "hype":     ["almost there!", "reset hype!!", "HERE IT COMES!", "so close!", "any moment!"],
    "refreshed": ["refreshed~", "brand new!", "recharged!", "lets go!", "reset!"],
    "studying": ["studying!", "practicing~", "learning!", "drilling~", "writing!"],
    "leveling": ["level up!!", "band up!!", "progress!!", "improving!!", "nice gain!!"],
}

# Analysis hints shown only when the language-coach plugin is active
ANALYSIS_HINTS = [
    "/language-review?", "check progress~", "run /language-review!", "see your stats!!",
]

# Cat faces for coaching moods
CAT_FACES_EXTRA = {
    "studying": ["ᓚᘏᗢ✏", "ᓚᘏ-ᗢ✏", "ᓚᘏᗢ✏"],
    "leveling": ["ᓚ₍ᘏ₎ᗢ↑", "ᓚ₍ᘏ₎ᗢ↑!", "ᓚ₍ᘏ₎ᗢ↑"],
}


def _load_coach_config(config_path: Optional[str] = None) -> dict:
    """Load language-coach config. Returns empty dict on any error."""
    path = Path(config_path) if config_path else Path.home() / ".claude" / "language-coach.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def _reminder_texts(config: dict) -> list[str]:
    """Build language-specific reminder texts from the coach config.

    Returns phrases like ["Use English!", "Write in English!", "Try English!"]
    based on the configured target language(s). Returns [] if no config.
    """
    # Multi-target: collect all target languages from targets list
    targets = config.get("targets")
    languages: list[str] = []
    if isinstance(targets, list):
        languages = [
            t["targetLanguage"]
            for t in targets
            if isinstance(t, dict) and t.get("targetLanguage")
        ]
    if not languages:
        lang = config.get("targetLanguage")
        if isinstance(lang, str) and lang:
            languages = [lang]
    if not languages:
        return []

    texts: list[str] = []
    for lang in languages:
        texts += [
            f"Use {lang}!",
            f"Write in {lang}!",
            f"Try {lang}!",
            f"Speak {lang}!",
            f"Practice {lang}!",
        ]
    return texts


def _load_language_progress(progress_path: Optional[str] = None) -> dict:
    """Load language progress JSON. Returns empty dict on any error."""
    path = Path(progress_path) if progress_path else Path.home() / ".claude" / "language-progress.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def _coaching_mood(progress: dict) -> Optional[str]:
    """Return a coaching-specific mood if language progress exists with recent data.

    Returns 'leveling' if any language improved in the last session,
    'studying' if progress data exists, or None if no progress data.
    """
    if not progress:
        return None
    for entry in progress.values():
        if not isinstance(entry, dict):
            continue
        estimates = entry.get("estimates", [])
        if len(estimates) >= 2:
            try:
                prev = float(estimates[-2].get("band", 0))
                curr = float(estimates[-1].get("band", 0))
                if curr > prev:
                    return "leveling"
            except (TypeError, ValueError):
                pass
    return "studying"


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


def _get_mood(pct: float, hour: int, minutes_to_reset: Optional[int] = None,
               warning_threshold: float = 30.0,
               critical_threshold: float = 70.0) -> str:
    """Determine pet mood from usage percentage, time of day, and reset proximity.

    Thresholds align with the bar's color ladder so the pet text and the bar
    color tell the same story:
      - pct <= warning/2  → chill   (well within safe zone)
      - pct <= warning    → working (still safe but engaged)
      - pct <= critical   → nervous (yellow zone)
      - pct > critical    → panic   (red zone)
    """
    # Reset hype overrides everything when usage is high
    if minutes_to_reset is not None and minutes_to_reset <= 30 and pct >= warning_threshold:
        return "hype"

    # Just reset — low usage after being high
    if pct <= 5:
        return "refreshed" if minutes_to_reset and minutes_to_reset > 280 else "chill"

    # Night time override for low usage
    if pct <= warning_threshold and (hour >= 23 or hour < 6):
        return "sleepy"

    # Usage-based mood — proportional to user's chosen thresholds
    if pct <= warning_threshold * 0.65:
        return "chill"
    if pct <= warning_threshold:
        return "working"
    if pct <= critical_threshold:
        return "nervous"
    return "panic"


def _get_frame_tick() -> int:
    """Get a frame index based on current time (changes every ~3 seconds).
    Kept for backward compatibility with anything that imports it; the
    multi-track animation engine in pet_animation no longer relies on it.
    """
    return int(time.time() / 3) % 3


def get_pet_face(mood: str, session_id: str = "") -> str:
    """Get the cat face for the current mood.

    Delegates to the multi-track time-driven animation engine in
    pet_animation.compose_face. Each call is one frame: tail position,
    aura particle, blink/ear-twitch state, breath phase — all functions
    of `time.time()` with independent periods. Two consecutive renders
    even ~50ms apart will look different, which is what makes the pet
    appear continuously alive whenever the user is active.
    """
    from . import pet_animation
    return pet_animation.compose_face(mood, time.time(), session_id=session_id)


def get_pet_status(mood: str, session_id: str = "", reminders: Optional[list[str]] = None) -> str:
    """Pick a status text for the mood. Stable within ~5s windows.

    When reminders are provided (language-specific nudges like "Use English!"),
    they are mixed into the pool at roughly 1-in-3 frequency.

    Use a deterministic hash (md5) instead of Python's built-in hash(): the
    builtin is salted per-process via PYTHONHASHSEED, which would make the
    "stable within a 5s window" promise break across separate cs invocations.
    """
    base_texts = STATUS_TEXTS.get(mood, STATUS_TEXTS["chill"])
    if reminders:
        # Weight: 2 base texts for every 1 reminder → ~33% reminder rate
        pool = base_texts + base_texts + reminders
    else:
        pool = base_texts
    window = int(time.time() / 5)
    seed_input = f"{window}:{session_id}".encode("utf-8")
    seed = int(hashlib.md5(seed_input).hexdigest()[:8], 16)
    rng = random.Random(seed)
    return rng.choice(pool)


def format_pet(
    pct: float,
    hour: int,
    session_id: str = "",
    minutes_to_reset: Optional[int] = None,
    custom_name: Optional[str] = None,
    progress_path: Optional[str] = None,
    coach_config_path: Optional[str] = None,
    warning_threshold: float = 30.0,
    critical_threshold: float = 70.0,
) -> str:
    """Build the full pet string for the status bar.

    Example: "ᓚᘏᗢ Pixel:working!"
    When language-progress data exists the pet enters a coaching-aware mood:
      studying → "ᓚᘏᗢ✏ Byte:studying!"
      leveling → "ᓚ₍ᘏ₎ᗢ↑ Byte:level up!!"
    Language reminders ("Use English!", "Write in Japanese!") are mixed in
    at ~33% frequency when the coach config is present and enabled.

    `warning_threshold` and `critical_threshold` are passed through so the
    pet mood ladder stays in sync with the bar color ladder (otherwise a
    user with --critical-threshold 80 would see a panicked pet on a calm
    green bar at pct=72).
    """
    name = get_pet_name(session_id, custom_name)
    mood = _get_mood(pct, hour, minutes_to_reset,
                      warning_threshold=warning_threshold,
                      critical_threshold=critical_threshold)

    # Load coach config for reminders (only when plugin is installed and enabled)
    coach_config = _load_coach_config(coach_config_path)
    reminders: Optional[list[str]] = None
    if coach_config.get("enabled", False):
        r = _reminder_texts(coach_config)
        # Mix language reminders + analysis hints into one pool
        reminders = (r + ANALYSIS_HINTS) if r else ANALYSIS_HINTS

    # Coaching mood overrides low-intensity base moods — only when plugin is active
    if mood in ("chill", "sleepy", "working") and coach_config.get("enabled", False):
        progress = _load_language_progress(progress_path)
        coaching = _coaching_mood(progress)
        if coaching:
            mood = coaching

    face = get_pet_face(mood, session_id=session_id)
    status = get_pet_status(mood, session_id, reminders=reminders)
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
