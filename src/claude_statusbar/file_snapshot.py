"""Bounded stat-keyed cache for small, infrequently edited JSON files."""
import json
from collections import OrderedDict
from copy import deepcopy

_cache = OrderedDict()


def read_json(path):
    st = path.stat()
    key = (str(path), st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)
    if key in _cache:
        _cache.move_to_end(key)
        return deepcopy(_cache[key])
    value = json.loads(path.read_text(encoding='utf-8'))
    _cache[key] = value
    while len(_cache) > 128:
        _cache.popitem(last=False)
    return deepcopy(value)
