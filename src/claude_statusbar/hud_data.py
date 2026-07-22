#!/usr/bin/env python3
"""P0 data layer for the desktop HUD.

- Official 5h/7d used% + reset countdowns from Claude Desktop's own
  plan-usage-history.json (sampled every 5 min; instant read).
- AgentParty status for the *current active session's project*, located by the
  most-recently-touched transcript, via the project's own party module.
"""
import json, time, sys, glob, os
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

PLAN_USAGE = Path.home() / "Library/Application Support/Claude/plan-usage-history.json"
PROJECTS = Path.home() / ".claude/projects"
FIVE_H = 5 * 3600
SEVEN_D = 7 * 24 * 3600
DROP = 15
STALE_S = 15 * 60
SESSION_ACTIVE_S = 600      # transcript touched within 10 min => "current session"

try:
    from .party import read_party_status, workspace_id  # same package
    _PARTY_OK = True
except Exception:
    _PARTY_OK = False


@dataclass
class Usage:
    fh: Optional[int] = None
    sd: Optional[int] = None
    org: str = ""
    sample_age_s: Optional[float] = None
    fh_reset_s: Optional[float] = None
    sd_reset_s: Optional[float] = None
    stale: bool = False
    err: str = ""
    # party
    project: str = ""
    party: Optional[Dict[str, Any]] = None    # None => no party in this project


# ---------- usage ----------
def _load_usage() -> List[Dict]:
    d = json.loads(PLAN_USAGE.read_text(encoding="utf-8"))
    return d.get("samples", [])


def _last_reset_ms(samples, key):
    last = None
    for i in range(1, len(samples)):
        a, b = samples[i - 1]["u"].get(key), samples[i]["u"].get(key)
        if a is None or b is None:
            continue
        if a - b >= DROP:
            last = samples[i]["t"]
    return last


def _countdown(samples, key, window_s, now):
    lr = _last_reset_ms(samples, key)
    if lr is None:
        return None
    r = lr / 1000 + window_s - now
    while r < 0:
        r += window_s
    return r


# ---------- party (current session's project) ----------
def _cwd_of(transcript: Path) -> Optional[str]:
    try:
        with open(transcript, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if '"cwd"' not in line:
                    continue
                o = json.loads(line)
                if o.get("cwd"):
                    return o["cwd"]
    except Exception:
        pass
    return None


def _active_session():
    """(transcript_path, cwd) of the most-recently-touched transcript, or None."""
    try:
        jsonls = sorted(PROJECTS.glob("*/*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    except Exception:
        return None
    if not jsonls:
        return None
    top = jsonls[0]
    if time.time() - top.stat().st_mtime > SESSION_ACTIVE_S:
        return None
    return top, _cwd_of(top)


def _party_for_project(now):
    if not _PARTY_OK:
        return "", None
    act = _active_session()
    if not act:
        return "", None
    top, cwd = act
    if not cwd:
        return "", None
    project = Path(cwd).name
    try:
        ps = read_party_status(cwd, now=now)
    except Exception:
        return project, None
    if ps is None:
        return project, None
    return project, {
        "channel": ps.channel,
        "identity": ps.identity_name,
        "unread": ps.unread,
        "last_from": ps.last_from,
        "last_preview": ps.last_preview,
        "last_age": ps.last_age,
        "live": ps.listener_alive and not ps.listener_stale,
        "present": ps.listener_present,
        "stale": ps.listener_stale,
        "mentioned": ps.mentioned,
        "fresh": ps.fresh,
    }


AGENTPARTY_STATE = Path.home() / ".agentparty/state"
CHANNEL_ACTIVE_S = 1800   # only channels touched within 30 min count as "active"


def all_channels(top_n: int = 3, max_age_s: int = CHANNEL_ACTIVE_S,
                 now: Optional[float] = None) -> List[Dict[str, Any]]:
    """All currently-active AgentParty channels, deduped by channel, ranked by
    unread-first then recency. Scans every workspace's statusline.json."""
    now = time.time() if now is None else now
    best: Dict[str, Dict[str, Any]] = {}
    try:
        files = AGENTPARTY_STATE.glob("*/statusline.json")
    except Exception:
        return []
    for f in files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        ch = d.get("channel")
        ua = d.get("updated_at", 0) or 0
        if not ch or (now - ua / 1000) > max_age_s:
            continue
        last = d.get("last_message") if isinstance(d.get("last_message"), dict) else {}
        rec = {
            "key": ch,
            "channel": ch,
            "identity": (d.get("identity") or {}).get("name", ""),
            "unread": d.get("unread", 0) or 0,
            "last_from": last.get("from", ""),
            "last_preview": last.get("preview", ""),
            "age_s": now - ua / 1000,
            "updated": ua,
            "ws": f.parent.name,            # workspace_id (statusline.json dir)
            "server": d.get("server", ""),  # for web fallback
        }
        if ch not in best or ua > best[ch]["updated"]:
            best[ch] = rec
    chans = sorted(best.values(), key=lambda r: (0 if r["unread"] else 1, r["age_s"]))
    return chans[:top_n]


def _ws_to_session_map() -> Dict[str, Any]:
    """workspace_id -> (cwd, latest_session_uuid), by scanning ~/.claude/projects.
    Lets a channel (which knows only its workspace_id) resolve to a resumable
    Claude session."""
    m: Dict[str, Any] = {}
    if not _PARTY_OK:
        return m
    try:
        projs = [p for p in PROJECTS.glob("*") if p.is_dir()]
    except Exception:
        return m
    for proj in projs:
        jsonls = sorted(proj.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not jsonls:
            continue
        cwd = _cwd_of(jsonls[0])
        if not cwd:
            continue
        try:
            m[workspace_id(cwd)] = (cwd, jsonls[0].stem)
        except Exception:
            continue
    return m


def channel_session(ws_id: str):
    """Resolve a channel's workspace_id to (cwd, session_uuid), or None."""
    return _ws_to_session_map().get(ws_id)


def snapshot(org: Optional[str] = None, now: Optional[float] = None) -> Usage:
    now = time.time() if now is None else now
    try:
        alls = _load_usage()
    except FileNotFoundError:
        u = Usage(err="plan-usage-history.json not found")
        u.project, u.party = _party_for_project(now)
        return u
    except Exception as e:
        return Usage(err=f"read failed: {e}")
    if not alls:
        return Usage(err="no samples")
    cur_org = org or alls[-1].get("org", "")
    s = [e for e in alls if e.get("org") == cur_org]
    last = s[-1]
    age = now - last["t"] / 1000
    u = Usage(
        fh=last["u"].get("fh"), sd=last["u"].get("sd"), org=cur_org,
        sample_age_s=age,
        fh_reset_s=_countdown(s, "fh", FIVE_H, now),
        sd_reset_s=_countdown(s, "sd", SEVEN_D, now),
        stale=age > STALE_S,
    )
    u.project, u.party = _party_for_project(now)
    return u


def fmt_dur(s):
    if s is None:
        return "—"
    s = int(s)
    h, m = s // 3600, (s % 3600) // 60
    if h >= 24:
        return f"{h//24}d{h%24}h"
    return f"{h}h{m:02d}m" if h else f"{m}m"


if __name__ == "__main__":
    u = snapshot()
    print("err:", u.err or "(none)")
    print(f"5h: {u.fh}%  reset {fmt_dur(u.fh_reset_s)}   |   7d: {u.sd}%  reset {fmt_dur(u.sd_reset_s)}")
    print(f"project: {u.project}   party: {u.party}")
