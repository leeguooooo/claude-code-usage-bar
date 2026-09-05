"""Bounded background collectors, shared by every session in the daemon."""
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
import time

_git_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='cs-git')
_network_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='cs-network')
_lock = Lock()
_pending = set()
_retry = {}


def submit(key, function, *args):
    with _lock:
        if key in _pending or len(_pending) >= 16:
            return False
        if time.monotonic() < _retry.get(key, 0):
            return False
        _pending.add(key)

    def run():
        try:
            function(*args)
        finally:
            with _lock:
                _pending.discard(key)
                _retry[key] = time.monotonic() + 30
                if len(_retry) > 256:
                    now = time.monotonic()
                    for k in list(_retry):
                        if _retry[k] < now:
                            del _retry[k]
    pool = _git_pool if key[0] == 'git' else _network_pool
    try:
        pool.submit(run)
    except RuntimeError:
        with _lock:
            _pending.discard(key)
        return False
    return True
