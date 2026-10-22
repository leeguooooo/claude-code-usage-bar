"""UI language for sentence-like status text (risk lines). zh | en.

`lang = auto` follows the OS. On macOS that is the first entry of
AppleLanguages, read straight from the global preferences plist — not $LANG,
which terminals commonly leave at en_US.UTF-8 even on a Chinese system.
Elsewhere LC_ALL / LC_MESSAGES / LANG decide. Labels, numbers and glyphs on
the bars are never translated.
"""
import os
import plistlib
import sys
import time
from pathlib import Path
from typing import Optional

SUPPORTED = ("zh", "en")
_TTL_S = 600.0
_cached: Optional[tuple] = None   # (lang, read_at) — the daemon is long-lived


def _normalize(tag: str) -> Optional[str]:
    tag = (tag or "").strip().lower()
    if not tag or tag in ("c", "posix"):
        return None
    return "zh" if tag.startswith("zh") else "en"


def _macos_lang() -> Optional[str]:
    p = Path.home() / "Library" / "Preferences" / ".GlobalPreferences.plist"
    try:
        with p.open("rb") as fh:
            langs = plistlib.load(fh).get("AppleLanguages")
    except Exception:
        return None
    if isinstance(langs, list) and langs and isinstance(langs[0], str):
        return _normalize(langs[0])
    return None


def system_lang(env=None) -> str:
    env = os.environ if env is None else env
    if sys.platform == "darwin":
        lang = _macos_lang()
        if lang:
            return lang
    for key in ("LC_ALL", "LC_MESSAGES", "LANG"):
        lang = _normalize(env.get(key, ""))
        if lang:
            return lang
    return "en"


def ui_lang(setting: str = "auto") -> str:
    """Resolve the `lang` config value to zh | en."""
    global _cached
    if setting in SUPPORTED:
        return setting
    now = time.time()
    if _cached is None or now - _cached[1] > _TTL_S:
        _cached = (system_lang(), now)
    return _cached[0]
