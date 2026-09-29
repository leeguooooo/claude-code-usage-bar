"""open-cross-session (ocs) line: `ocs boss · claude-7d5a5d07 · ✉3 · lan win`.

Shows this session's ocs name + stable id so other agents can `ocs dm` it,
plus its unread DM count and the LAN bridge state. The only interfaces we
depend on are the ocs CLI's JSON output — ``ocs whoami --json --session <sid>``,
``ocs inbox --json --session <sid>`` (ocs >= 0.6.6) and ``ocs lan status --json``
— never ~/.ocs internals, whose format ocs reserves the right to change. Each
extra part hides on its own when its command fails (older ocs, LAN never set up).

Render path only reads a per-session TTL cache; a stale cache kicks off a
refresh (daemon: bounded thread pool; inline: detached ``-m claude_statusbar.ocs``
subprocess), exactly like the git dirty-state refresh. The segment hides
whenever ocs is missing, older than 0.5.0, or doesn't know the session (exit 1).

Module top stays import-light (no subprocess / shutil) — it's imported on the
per-second render path.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from datetime import datetime
from typing import Optional

# Short enough that `ocs rename` shows up within half a minute.
TTL_SECONDS = 30
INFLIGHT_MAX_AGE_S = 30
# A paired peer is drawn as recently seen when ocs heard from it this recently.
PEER_RECENT_S = 10 * 60
MAX_PEERS_SHOWN = 3
_SID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _cache_root() -> Path:
    return Path(os.path.expanduser("~")) / ".cache" / "claude-statusbar" / "ocs"


def cache_path_for(session_id: str) -> Path:
    h = hashlib.sha1(session_id.encode("utf-8")).hexdigest()
    return _cache_root() / f"{h}.json"


def _ocs_names() -> list:
    """Candidate file names. On Windows the binary is ``ocs.exe`` (or a
    ``.cmd`` shim) — honour PATHEXT like ``shutil.which`` does, and skip a
    bare ``ocs`` there since CreateProcess can't run an extensionless file."""
    if os.name != "nt":
        return ["ocs"]
    exts = os.environ.get("PATHEXT") or ".COM;.EXE;.BAT;.CMD"
    return ["ocs" + e.lower() for e in exts.split(";") if e]


def find_ocs() -> Optional[str]:
    """PATH first, then ~/.local/bin/ocs (the installer's default target,
    which Claude Code's statusLine environment often lacks on PATH)."""
    names = _ocs_names()
    dirs = [d for d in os.environ.get("PATH", "").split(os.pathsep) if d]
    dirs.append(os.path.join(os.path.expanduser("~"), ".local", "bin"))
    for d in dirs:
        for name in names:
            p = os.path.join(d, name)
            if os.path.isfile(p) and os.access(p, os.X_OK):
                return p
    return None


def read_cache(session_id: str) -> Optional[dict]:
    try:
        return json.loads(cache_path_for(session_id).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def is_fresh(entry: Optional[dict], now: Optional[float] = None) -> bool:
    if not isinstance(entry, dict):
        return False
    ts = entry.get("ts")
    if not isinstance(ts, (int, float)):
        return False
    age = (time.time() if now is None else now) - ts
    return 0 <= age < TTL_SECONDS


def write_cache_atomic(session_id: str, entry: dict) -> None:
    p = cache_path_for(session_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=f".{p.name}.",
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(entry))
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _inflight_path(session_id: str) -> Path:
    return cache_path_for(session_id).with_suffix(".inflight")


def is_inflight(session_id: str) -> bool:
    try:
        data = json.loads(_inflight_path(session_id).read_text(encoding="utf-8"))
        ts = float(data.get("ts", 0))
    except (OSError, json.JSONDecodeError, ValueError, TypeError, AttributeError):
        return False
    return (time.time() - ts) < INFLIGHT_MAX_AGE_S


def mark_inflight(session_id: str) -> None:
    p = _inflight_path(session_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"pid": os.getpid(), "ts": time.time()}),
                 encoding="utf-8")


def clear_inflight(session_id: str) -> None:
    try:
        _inflight_path(session_id).unlink()
    except FileNotFoundError:
        pass


def try_claim(session_id: str):
    """Kernel lock held through the refresh; released even if we crash."""
    p = cache_path_for(session_id).with_suffix(".lock")
    p.parent.mkdir(parents=True, exist_ok=True)
    fh = p.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    return fh


def _clean(value) -> Optional[str]:
    """A printable single-token string, or None. whoami output ends up on the
    terminal, so control chars / escapes must never pass through."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > 64 or not value.isprintable():
        return None
    return value


def parse_whoami(stdout: str) -> Optional[dict]:
    """``{"id","name","session",...}`` → ``{"id","name"}`` for display.

    ``id`` falls back to ``session`` (ocs gives a null id when the sessionId
    doesn't start with hex). Returns None when there's nothing addressable.
    """
    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    ident = _clean(data.get("id")) or _clean(data.get("session"))
    if ident is None:
        return None
    name = _clean(data.get("name"))
    if name == ident:
        name = None
    return {"id": ident, "name": name}


def parse_inbox(stdout: str) -> Optional[int]:
    """``ocs inbox --json`` thread list → total unread count, or None."""
    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, list):
        return None
    total = 0
    for thread in data:
        n = thread.get("unread") if isinstance(thread, dict) else None
        if isinstance(n, int) and not isinstance(n, bool) and n > 0:
            total += n
    return total


def _iso_to_epoch(value) -> Optional[float]:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def parse_lan_status(stdout: str) -> Optional[dict]:
    """``ocs lan status --json`` → ``{"running", "peers": [{"label","seen"}]}``."""
    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("running"), bool):
        return None
    peers = []
    raw_peers = data.get("peers")
    for peer in raw_peers if isinstance(raw_peers, list) else []:
        if not isinstance(peer, dict):
            continue
        label = _clean(peer.get("label")) or _clean(peer.get("name"))
        if label is None:
            continue
        peers.append({"label": label, "seen": _iso_to_epoch(peer.get("last_seen"))})
    return {"running": data["running"], "peers": peers}


def _run_json(exe: str, args: list, timeout_s: float, parse):
    """Run one ocs subcommand; parsed stdout on exit 0, else None."""
    import subprocess  # lazy — keep the render path import-light
    try:
        proc = subprocess.run(
            [exe, *args],
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=timeout_s,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return parse(proc.stdout) if proc.returncode == 0 else None


def refresh(session_id: str, timeout_s: float = 2.0) -> None:
    lock = try_claim(session_id)
    if lock is None:
        return
    try:
        if not is_fresh(read_cache(session_id)):
            _refresh_locked(session_id, timeout_s)
    finally:
        lock.close()
        clear_inflight(session_id)


def _refresh_locked(session_id: str, timeout_s: float) -> None:
    entry = {"ts": time.time(), "ok": False}
    exe = find_ocs()
    if exe is not None:
        parsed = _run_json(exe, ["whoami", "--json", "--session", session_id],
                           timeout_s, parse_whoami)
        if parsed is not None:
            entry.update(ok=True, **parsed)
            # Unknown flag on ocs < 0.6.6 → non-zero exit → no unread part.
            entry["unread"] = _run_json(
                exe, ["inbox", "--json", "--session", session_id],
                timeout_s, parse_inbox)
            entry["lan"] = _run_json(exe, ["lan", "status", "--json"],
                                     timeout_s, parse_lan_status)
    write_cache_atomic(session_id, entry)


def format_label(entry: Optional[dict]) -> str:
    """`boss · claude-7d5a5d07` / `claude-7d5a5d07` — "" when not addressable."""
    if not isinstance(entry, dict) or not entry.get("ok"):
        return ""
    ident = _clean(entry.get("id"))
    if ident is None:
        return ""
    name = _clean(entry.get("name"))
    return f"{name} · {ident}" if name else ident


def format_unread(entry: Optional[dict]) -> Optional[int]:
    """Unread DM count worth showing (> 0), else None."""
    if not isinstance(entry, dict) or not entry.get("ok"):
        return None
    n = entry.get("unread")
    if isinstance(n, int) and not isinstance(n, bool) and n > 0:
        return n
    return None


def format_lan(entry: Optional[dict], now: Optional[float] = None) -> Optional[dict]:
    """``{"running", "peers": [(label, recent)], "more"}`` for display, or None
    when the LAN bridge is neither running nor paired with anyone."""
    if not isinstance(entry, dict) or not entry.get("ok"):
        return None
    lan = entry.get("lan")
    if not isinstance(lan, dict):
        return None
    running = lan.get("running") is True
    raw = lan.get("peers") if isinstance(lan.get("peers"), list) else []
    now = time.time() if now is None else now
    peers = []
    for peer in raw:
        if not isinstance(peer, dict):
            continue
        label = _clean(peer.get("label"))
        if label is None:
            continue
        seen = peer.get("seen")
        recent = (isinstance(seen, (int, float))
                  and 0 <= now - seen < PEER_RECENT_S)
        peers.append((label, bool(recent)))
    if not running and not peers:
        return None
    # Recently seen peers first, so the cap never hides the reachable ones.
    peers.sort(key=lambda p: not p[1])
    return {"running": running, "peers": peers[:MAX_PEERS_SHOWN],
            "more": max(0, len(peers) - MAX_PEERS_SHOWN)}


def ocs_status(session_id: str) -> dict:
    """Unread count + LAN state from the same cache ``ocs_label`` keeps fresh.
    Call after ``ocs_label``; never spawns anything itself."""
    if not session_id or not _SID_RE.match(session_id):
        return {"unread": None, "lan": None}
    entry = read_cache(session_id)
    return {"unread": format_unread(entry), "lan": format_lan(entry)}


def ocs_label(session_id: str, *, spawn: bool = True) -> str:
    """Cached ocs label for this session; never blocks on ocs.

    Returns the last known label (possibly up to one refresh stale) while a
    background refresh runs, "" when ocs isn't installed or can't resolve the
    session.
    """
    if not session_id or not _SID_RE.match(session_id):
        return ""
    entry = read_cache(session_id)
    if is_fresh(entry):
        return format_label(entry)
    if find_ocs() is None:
        return ""
    if spawn:
        from . import identity as _identity
        if _identity._BACKGROUND_COLLECTORS:
            from .refresh_pool import submit
            submit(("ocs", session_id), refresh, session_id)
        elif not is_inflight(session_id):
            mark_inflight(session_id)
            try:
                import subprocess  # lazy
                subprocess.Popen(
                    [sys.executable, "-m", "claude_statusbar.ocs", session_id],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, close_fds=True,
                    start_new_session=True,
                )
            except (OSError, ValueError):
                clear_inflight(session_id)
    return format_label(entry)


def main(argv) -> int:
    if len(argv) >= 2 and _SID_RE.match(argv[1]):
        try:
            refresh(argv[1])
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
