"""Quota-only snapshots. Never infer ownership from a global debug payload."""
import hashlib
import json
import time
from pathlib import Path

MAX_AGE_SECONDS = 600


def path_for(data):
    from .predict import account_id
    account = account_id(data.get('transcript_path') or None)
    sid = data.get('session_id')
    if account:
        owner = 'account:' + account
    elif isinstance(sid, str) and sid.strip():
        owner = 'session:' + sid
    else:
        return None
    name = hashlib.sha256(owner.encode()).hexdigest()
    return Path.home() / '.cache' / 'claude-statusbar' / 'quota' / (name + '.json')


def remember(data):
    path = path_for(data)
    if path is None:
        return
    limits = data.get('rate_limits')
    if not isinstance(limits, dict):
        return
    snapshot = {key: limits[key] for key in ('five_hour', 'seven_day')
                if isinstance(limits.get(key), dict) and limits[key]}
    if not snapshot:
        return
    from .cache import atomic_write_text, file_transaction
    try:
        with file_transaction(path):
            try:
                old = json.loads(path.read_text(encoding='utf-8'))
                if old.get('rate_limits') == snapshot:
                    return
            except (OSError, ValueError, AttributeError):
                pass
            atomic_write_text(path, json.dumps({'ts': time.time(), 'rate_limits': snapshot}),
                              durable=False)
    except OSError:
        pass


def read(data):
    path = path_for(data)
    if path is None:
        return {}
    try:
        snapshot = json.loads(path.read_text(encoding='utf-8'))
        if not 0 <= time.time() - float(snapshot['ts']) <= MAX_AGE_SECONDS:
            return {}
        limits = snapshot.get('rate_limits')
        return limits if isinstance(limits, dict) else {}
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return {}
