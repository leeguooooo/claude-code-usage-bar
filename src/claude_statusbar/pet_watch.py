"""Daemon-mode pet renderer.

The statusLine path is a slave to Claude Code's redraw cadence: when the
user idles, our pet freezes. This module sidesteps that by running a
self-driven loop that redraws on the same terminal line at a fixed FPS.

Run it in a tmux pane / iTerm split / second terminal:

    cs pet --watch          # default 12 FPS
    cs pet --watch --fps 30 # smoother
    cs pet --watch --once   # one frame, useful for tests

Live data
---------
Reads ``~/.cache/claude-statusbar/last_stdin.json`` once per second to keep
the cat's mood/stats in sync with Anthropic's headers. We don't read every
frame — that's a 30 FPS file IO storm we don't need.

Terminal hygiene
----------------
- Hides the cursor while running, restores on exit.
- Uses ``\\r`` + ``\\x1b[K`` to overwrite the same line.
- Cleans up on SIGINT (Ctrl+C) and SIGTERM.
"""

from __future__ import annotations

import json
import math
import os
import signal
import sys
import time
from pathlib import Path
from typing import Optional

from . import pet_animation


# ANSI helpers — we keep our own minimal set instead of pulling progress.py.
_HIDE_CURSOR = "\x1b[?25l"
_SHOW_CURSOR = "\x1b[?25h"
_CLEAR_LINE  = "\x1b[2K\r"   # clear whole line + return cursor


_STDIN_CACHE = Path.home() / ".cache" / "claude-statusbar" / "last_stdin.json"


def _read_live_data() -> dict:
    """Pull the most recent stdin payload claude-statusbar has cached.
    Returns {} if nothing's there yet."""
    try:
        return json.loads(_STDIN_CACHE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _mood_from(data: dict) -> str:
    """Crude mood derivation from the cached stdin. Doesn't try to be as
    smart as core.main — this daemon is a passenger, not a driver."""
    rl = (data.get("rate_limits") or {}).get("five_hour") or {}
    pct = rl.get("used_percentage", 0)
    try:
        pct = float(pct)
    except (TypeError, ValueError):
        pct = 0.0
    if pct >= 70: return "panic"
    if pct >= 30: return "nervous"
    if pct >= 19.5: return "working"
    return "chill"


def _format_line(data: dict, t: float, session_id: str = "") -> str:
    """Build a single output line: pet + mood + small data summary."""
    mood = _mood_from(data)
    face = pet_animation.compose_face(mood, t, session_id=session_id)
    rl = (data.get("rate_limits") or {}).get("five_hour") or {}
    sd = (data.get("rate_limits") or {}).get("seven_day") or {}
    pct5 = int(round(float(rl.get("used_percentage") or 0)))
    pct7 = int(round(float(sd.get("used_percentage") or 0)))
    return f"{face}  5h {pct5:>3}%  ·  7d {pct7:>3}%  ·  {mood}"


# --- public entry point ---------------------------------------------------

def run(fps: int = 12, once: bool = False) -> int:
    """Run the watch loop. Returns process exit code.

    fps  — frames per second; clamped to [1, 60]
    once — render exactly one frame and exit (for tests / smoke checks)
    """
    fps = max(1, min(60, int(fps)))
    frame_dt = 1.0 / fps

    if once:
        line = _format_line(_read_live_data(), time.time())
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
        return 0

    # Refresh live data every ~1s, not every frame.
    refresh_dt = 1.0
    data = _read_live_data()
    last_refresh = time.time()
    session_id = (data.get("session_id") or "watch")

    stop = {"flag": False}

    def _on_sig(signum, frame):
        stop["flag"] = True
    signal.signal(signal.SIGINT, _on_sig)
    signal.signal(signal.SIGTERM, _on_sig)

    sys.stdout.write(_HIDE_CURSOR)
    sys.stdout.flush()
    try:
        while not stop["flag"]:
            now = time.time()
            if now - last_refresh >= refresh_dt:
                data = _read_live_data()
                last_refresh = now
                # Keep the live session_id if it changes so the cat's
                # blink/twitch RNG tracks the user's actual session.
                session_id = data.get("session_id") or session_id

            line = _format_line(data, now, session_id=session_id)
            sys.stdout.write(_CLEAR_LINE + line)
            sys.stdout.flush()

            # Sleep until the next frame. math.fmod handles drift gently.
            sleep_for = frame_dt - ((time.time() - now))
            if sleep_for > 0:
                time.sleep(sleep_for)
    finally:
        sys.stdout.write(_CLEAR_LINE + _SHOW_CURSOR + "\n")
        sys.stdout.flush()
    return 0
