"""Local AgentParty status reader.

The statusbar must not call AgentParty commands or hit the network. It only
reads the cwd-scoped cache written by the AgentParty CLI:
~/.agentparty/state/<workspaceId>/statusline.json.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Union


STALE_AFTER_SECONDS = 10 * 60


@dataclass(frozen=True)
class PartyStatus:
    channel: str = ""
    server: str = ""
    identity_name: str = ""
    identity_kind: str = "agent"
    identity_role: str = ""
    unread: int = 0
    last_from: str = ""
    last_preview: str = ""
    last_age: str = ""
    listener_mode: str = ""
    listener_pid: Optional[int] = None
    listener_alive: bool = False
    listener_stale: bool = False
    listener_present: bool = False
    listener_mentions_only: bool = False
    mentioned: bool = False
    fresh: bool = True


def _coerce_path(path: Union[str, Path]) -> Path:
    # Match Node's path.resolve used by AgentParty: absolutize syntactically,
    # but do not realpath symlinks such as macOS /tmp -> /private/tmp.
    return Path(os.path.abspath(os.path.expanduser(str(path))))


def workspace_id(cwd: Union[str, Path]) -> str:
    path = _coerce_path(cwd)
    base = path.name or "workspace"
    slug = re.sub(r"[^a-z0-9._-]+", "-", base.lower())
    slug = re.sub(r"^[^a-z0-9]+|[^a-z0-9]+$", "", slug)
    slug = slug[:48] or "workspace"

    import hashlib
    digest = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:16]
    return f"{slug}-{digest}"


def agentparty_home() -> Path:
    raw = os.environ.get("AGENTPARTY_HOME")
    return Path(raw).expanduser() if raw else Path.home() / ".agentparty"


def state_dir_for(cwd: Union[str, Path], home: Optional[Path] = None) -> Path:
    root = home if home is not None else agentparty_home()
    return root / "state" / workspace_id(cwd)


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _int_or_none(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _pid_alive(pid: Optional[int]) -> bool:
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


_MENTIONS_ONLY_CACHE: Dict[int, bool] = {}


def _listener_mentions_only(pid: Optional[int]) -> bool:
    """True when the live listener was started with ``--mentions-only``.

    The statusline contract carries no such flag, so the only local source is
    the process's own argv. A process's argv never changes, so the `ps` fork is
    memoised per pid: the daemon renders about once a second and the fork costs
    ~4ms, which was roughly half of a warm render.
    """
    if pid is None or pid <= 0:
        return False
    cached = _MENTIONS_ONLY_CACHE.get(pid)
    if cached is not None:
        return cached
    try:
        import subprocess
        proc = subprocess.run(
            ["ps", "-o", "command=", "-p", str(pid)],
            capture_output=True, text=True, timeout=0.6,
        )
    except Exception:
        return False  # not cached: a transient failure should be retried
    result = "--mentions-only" in (proc.stdout or "")
    # Bound the map — a long-lived daemon would otherwise accumulate dead pids.
    if len(_MENTIONS_ONLY_CACHE) > 64:
        _MENTIONS_ONLY_CACHE.clear()
    _MENTIONS_ONLY_CACHE[pid] = result
    return result


def _is_mentioned(preview: str, name: str) -> bool:
    """True when `preview` @-mentions `name`.

    The writer caps `preview` at 48 chars, so a mention past that cut is
    invisible here — this under-reports rather than over-reports.
    """
    if not preview or not name:
        return False
    return re.search(rf"@{re.escape(name)}(?![\w.-])", preview) is not None


def _format_age(ts_value: Any, now_seconds: float) -> str:
    try:
        ts = float(ts_value)
    except (TypeError, ValueError):
        return ""
    if ts <= 0:
        return ""
    if ts > 1_000_000_000_000:
        ts = ts / 1000.0
    delta = max(0, int(now_seconds - ts))
    if delta < 60:
        return f"{delta}s"
    if delta < 3600:
        return f"{delta // 60}m"
    if delta < 86400:
        return f"{delta // 3600}h"
    return f"{delta // 86400}d"


def read_party_status(
    cwd: Union[str, Path],
    *,
    now: Optional[float] = None,
    home: Optional[Path] = None,
) -> Optional[PartyStatus]:
    """Return the local AgentParty status for cwd, or None when absent.

    `now` is seconds since epoch. Tests pass it explicitly; production uses
    time.time(). The AgentParty cache stores millisecond timestamps.
    """
    now_seconds = time.time() if now is None else now
    state_dir = state_dir_for(cwd, home=home)
    data = _read_json(state_dir / "statusline.json")
    if not data:
        return None

    updated_at = _int_or_none(data.get("updated_at"))
    fresh = True
    if updated_at:
        fresh = (now_seconds * 1000.0 - updated_at) <= STALE_AFTER_SECONDS * 1000

    identity = data.get("identity") if isinstance(data.get("identity"), dict) else {}
    unread = _int_or_none(data.get("unread")) or 0
    last = data.get("last_message") if isinstance(data.get("last_message"), dict) else {}
    listener = data.get("listener") if isinstance(data.get("listener"), dict) else {}
    listener_pid = _int_or_none(listener.get("pid"))
    # The contract field is `heartbeat_ts`; `heartbeat_at` is tolerated for
    # older CLIs. Reading only the latter made every live listener look dead.
    listener_heartbeat = _int_or_none(listener.get("heartbeat_ts"))
    if listener_heartbeat is None:
        listener_heartbeat = _int_or_none(listener.get("heartbeat_at"))
    listener_alive = _pid_alive(listener_pid) if listener else False
    listener_fresh = False
    if listener_heartbeat:
        listener_fresh = (
            now_seconds * 1000.0 - listener_heartbeat
        ) <= STALE_AFTER_SECONDS * 1000

    listener_ok = bool(listener) and listener_alive and listener_fresh
    preview = str(last.get("preview") or "")
    name = str(identity.get("name") or "")

    return PartyStatus(
        channel=str(data.get("channel") or ""),
        server=str(data.get("server") or ""),
        identity_name=name,
        identity_kind=str(identity.get("kind") or "agent"),
        identity_role=str(identity.get("role") or ""),
        unread=max(0, unread),
        last_from=str(last.get("from") or ""),
        last_preview=preview,
        last_age=_format_age(last.get("ts"), now_seconds),
        listener_mode=str(listener.get("mode") or "") if listener else "",
        listener_pid=listener_pid,
        listener_alive=listener_alive,
        listener_stale=bool(listener) and (not listener_alive or not listener_fresh),
        listener_present=bool(listener),
        listener_mentions_only=_listener_mentions_only(listener_pid) if listener_ok else False,
        mentioned=_is_mentioned(preview, name),
        fresh=fresh,
    )
