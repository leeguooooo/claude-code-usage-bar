"""Persistent isolated renderer; stdout is a private JSON-lines protocol."""
import json
import sys


def main():
    from .daemon import _render_payload
    from . import identity
    identity._BACKGROUND_COLLECTORS = True
    for line in sys.stdin:
        try:
            payload = json.loads(line)
            rendered = _render_payload(payload)
        except Exception:
            rendered = None
        print(json.dumps(rendered), flush=True)


if __name__ == '__main__':
    main()
