"""Persistent pet identity.

Why this exists
---------------
Until v2.9.4 the pet's name was a deterministic function of the current
Claude Code session_id (md5 → pick from PET_NAMES). New session = new
session_id = different name. From the user's POV that's not a pet — that's
a parade of strangers wearing the same costume.

Real pets are persistent: same name every day, age you can watch grow,
small landmarks (it's been 30 days, it's their anniversary). All of that
needs ONE source of truth that survives across cs invocations.

This module owns that source of truth: ``~/.cache/claude-statusbar/pet.json``.

Schema (forward-compatible — unknown keys are preserved on save)
----------------------------------------------------------------
    {
      "name": "Tofu",
      "first_seen": "2026-04-15T10:30:00+00:00",
      "last_session_id": "abc-123",
      "total_sessions": 47
    }

Operations
----------
- ``load_state(path)``    — read and return PersistentPet (defaults if missing)
- ``save_state(...)``     — atomic write
- ``ensure_identity(...)``— first-call effect: pick a name, set first_seen
- ``record_session(...)`` — bump total_sessions when session_id changes
- ``bond_age_days(...)``  — int days since first_seen (timezone-safe)
- ``bond_marker(...)``    — '' / '♡' / '♡♡' / '♡♡♡' by age tier
- ``milestone_emoji(...)``— '🎂' on anniversary, '✨' on session 100/500/1000
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

from .cache import atomic_write_text

STATE_PATH = Path.home() / ".cache" / "claude-statusbar" / "pet.json"


# ---------------------------------------------------------------------------
# Pet name pool — kept in lockstep with pet.PET_NAMES so existing
# session-deterministic names survive the migration. (See ensure_identity:
# we seed name pick from session_id when no state file exists, so a brand
# new install on an existing session yields the same name as before.)
# ---------------------------------------------------------------------------
_NAMES = (
    "Mochi", "Neko", "Pixel", "Byte", "Chip", "Tux", "Null", "Bit",
    "Tofu", "Ping", "Dash", "Flux", "Giga", "Nano", "Zap", "Boop",
    "Fizz", "Watt", "Hex", "Pico",
)


@dataclass
class PersistentPet:
    name: str = ""
    first_seen: str = ""
    last_session_id: str = ""
    total_sessions: int = 0

    @property
    def has_identity(self) -> bool:
        return bool(self.name and self.first_seen)


def load_state(path: Optional[Path] = None) -> PersistentPet:
    """Read pet state. Returns an empty PersistentPet on missing/corrupt file
    so callers can rely on a non-None return.

    Default arg deliberately resolves STATE_PATH at *call* time, not def
    time — otherwise tests that monkeypatch STATE_PATH would silently miss.
    """
    if path is None:
        path = STATE_PATH
    if not path.exists():
        return PersistentPet()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return PersistentPet()
    if not isinstance(raw, dict):
        return PersistentPet()
    return PersistentPet(
        name=str(raw.get("name", "")),
        first_seen=str(raw.get("first_seen", "")),
        last_session_id=str(raw.get("last_session_id", "")),
        total_sessions=int(raw.get("total_sessions", 0) or 0),
    )


def save_state(state: PersistentPet, path: Optional[Path] = None) -> bool:
    """Atomic write so a Ctrl+C mid-write never corrupts the file. Returns
    True on success — callers ignore failure (we'd rather lose a session
    bump than crash the statusLine).

    Default path resolves STATE_PATH at call time (see load_state)."""
    if path is None:
        path = STATE_PATH
    return atomic_write_text(path, json.dumps(asdict(state), indent=2) + "\n")


def _pick_initial_name(session_id: str, custom: Optional[str] = None) -> str:
    """Pick a name on first install. Custom name wins; otherwise we seed the
    RNG from session_id (md5 — deterministic across processes) so the SAME
    user on the SAME session keeps whatever name pet.get_pet_name historically
    produced. This makes the v2.9.4 migration a no-op visually."""
    if custom:
        return custom
    if session_id:
        seed = int(hashlib.md5(session_id.encode("utf-8")).hexdigest()[:8], 16)
    else:
        seed = 42
    return random.Random(seed).choice(_NAMES)


def ensure_identity(
    state: PersistentPet,
    session_id: str = "",
    custom_name: Optional[str] = None,
    now_iso: Optional[str] = None,
) -> Tuple[PersistentPet, bool]:
    """Make sure state has a name + first_seen. Returns (new_state, changed)."""
    if state.has_identity and not custom_name:
        return state, False

    new_name = custom_name or state.name or _pick_initial_name(session_id, custom_name)
    new_first_seen = state.first_seen or (now_iso or _now_iso())
    new = PersistentPet(
        name=new_name,
        first_seen=new_first_seen,
        last_session_id=state.last_session_id,
        total_sessions=state.total_sessions,
    )
    return new, (new != state)


def record_session(state: PersistentPet, session_id: str) -> Tuple[PersistentPet, bool]:
    """Bump total_sessions iff session_id is new. Returns (new_state, changed)."""
    if not session_id:
        return state, False
    if state.last_session_id == session_id:
        return state, False
    new = PersistentPet(
        name=state.name,
        first_seen=state.first_seen,
        last_session_id=session_id,
        total_sessions=state.total_sessions + 1,
    )
    return new, True


# ---------------------------------------------------------------------------
# Bond markers
# ---------------------------------------------------------------------------
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def bond_age_days(state: PersistentPet, now: Optional[datetime] = None) -> int:
    """Days since first_seen. 0 if state has no first_seen yet."""
    fs = _parse_iso(state.first_seen)
    if fs is None:
        return 0
    if fs.tzinfo is None:
        fs = fs.replace(tzinfo=timezone.utc)
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    delta = now - fs
    return max(0, int(delta.total_seconds() // 86400))


def bond_marker(days: int) -> str:
    """Three-tier bond glyph. <7d → none, ≥7d → ♡, ≥30d → ♡♡, ≥100d → ♡♡♡."""
    if days >= 100: return "♡♡♡"
    if days >= 30:  return "♡♡"
    if days >= 7:   return "♡"
    return ""


def milestone_emoji(state: PersistentPet, now: Optional[datetime] = None) -> str:
    """Returns a one-shot emoji for special days:
       - 🎂 on the anniversary of first_seen (matches month + day, ≥1 year old)
       - ✨ when total_sessions hits 100, 500, or 1000 (any of these last_session)
    Empty string otherwise.
    """
    fs = _parse_iso(state.first_seen)
    if fs is not None:
        if fs.tzinfo is None:
            fs = fs.replace(tzinfo=timezone.utc)
        n = (now or datetime.now(timezone.utc))
        if n.tzinfo is None:
            n = n.replace(tzinfo=timezone.utc)
        if n >= fs and (n.month, n.day) == (fs.month, fs.day) and (n - fs).days >= 365:
            return "🎂"

    if state.total_sessions in (100, 500, 1000):
        return "✨"
    return ""
