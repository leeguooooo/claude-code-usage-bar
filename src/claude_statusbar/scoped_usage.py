"""Opt-in model caps. Credentials and HTTPS are confined to background work."""
import hashlib
import json
import math
import time
from datetime import datetime
from pathlib import Path


def _path(account):
    key = hashlib.sha256(account.encode()).hexdigest()
    return Path.home() / '.cache' / 'claude-statusbar' / 'scoped' / (key + '.json')


def parse_limits(data):
    result = []
    if not isinstance(data, dict) or not isinstance(data.get('limits'), list):
        return result
    for row in data['limits']:
        try:
            if row.get('kind') != 'weekly_scoped':
                continue
            label = row['scope']['model']['display_name']
            pct = float(row['percent'])
            reset = datetime.fromisoformat(row['resets_at'].replace('Z', '+00:00')).timestamp()
            if not isinstance(label, str) or not label or len(label) > 40:
                continue
            if any(ord(c) < 32 or ord(c) == 127 for c in label):
                continue
            if not math.isfinite(pct) or not 0 <= pct <= 100 or not math.isfinite(reset):
                continue
            result.append(dict(label=label, percent=pct, resets_at=reset))
        except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
            continue
    return result[:8]


def _token():
    try:
        text = (Path.home() / '.claude' / '.credentials.json').read_text()
    except OSError:
        import sys
        if sys.platform != 'darwin':
            return None
        import subprocess
        # Token stays on a private pipe, never in argv, logs, or a cache.
        p = subprocess.run(['/usr/bin/security', 'find-generic-password',
                            '-s', 'Claude Code-credentials', '-w'],
                           capture_output=True, text=True, timeout=2)
        if p.returncode:
            return None
        text = p.stdout
    data = json.loads(text).get('claudeAiOauth', {})
    return data.get('accessToken')


def refresh(account):
    from .git_cache import try_claim
    from .predict import account_id
    from .cache import atomic_write_text
    path = _path(account)
    lock = try_claim('scoped:' + account)
    if lock is None:
        return
    try:
        try:
            old = json.loads(path.read_text())
            if 0 <= time.time() - old['ts'] < 300:
                return
        except (OSError, ValueError, KeyError, TypeError):
            pass
        if account_id() != account:
            return
        limits = []
        try:
            token = _token()
            if not isinstance(token, str) or not token:
                raise ValueError('missing credentials')
            from urllib.request import Request, build_opener, HTTPRedirectHandler
            class NoRedirect(HTTPRedirectHandler):
                def redirect_request(self, *args, **kwargs):
                    return None
            req = Request('https://api.anthropic.com/api/oauth/usage', headers={
                'Authorization': 'Bearer ' + token,
                'anthropic-beta': 'oauth-2025-04-20'})
            with build_opener(NoRedirect).open(req, timeout=3) as response:
                limits = parse_limits(json.loads(response.read(1024 * 1024)))
        except Exception:
            pass  # Negative-cache failures; never expose credentials/errors.
        if account_id() == account:
            atomic_write_text(path, json.dumps(dict(ts=time.time(), limits=limits)))
    finally:
        lock.close()


def cached_limits(*, spawn=True):
    from .predict import account_id
    account = account_id()
    if not account:
        return []
    try:
        data = json.loads(_path(account).read_text())
        age = time.time() - data['ts']
    except (OSError, ValueError, KeyError, TypeError):
        data, age = {}, float('inf')
    if spawn and not 0 <= age < 300:
        from .refresh_pool import submit
        submit(('scoped', account), refresh, account)
    return data.get('limits', []) if 0 <= age < 600 else []


def render_limits(limits, theme, use_color, warning, critical, projection=True):
    from .progress import _build_dimension, _fg, _render_projection
    from .predict import project_window, format_eta
    from .progress import window_severity_rgb
    parts = []
    now = time.time()
    if not isinstance(limits, list):
        return ''
    for row in limits:
        try:
            pct = float(row['percent'])
            remaining = float(row['resets_at']) - now
            label = row['label']
            if not isinstance(label, str) or any(ord(c) < 32 or ord(c) == 127 for c in label):
                continue
            if not math.isfinite(pct) or not 0 <= pct <= 100 or not math.isfinite(remaining):
                continue
        except (TypeError, KeyError, ValueError):
            continue
        if remaining <= 0:
            continue
        estimate = project_window(pct, remaining, 7 * 86400) if projection else None
        chip = '' if estimate is None else f'→{min(100, round(estimate[0]))}%'
        if estimate and estimate[1] < remaining:
            chip += '·' + format_eta(estimate[1])
        rgb = window_severity_rgb(pct, chip, theme, warning, critical) or theme.mute
        bar = _build_dimension(label, pct, _fg(rgb), use_color,
                               warning, critical, theme, fill_rgb=rgb)
        parts.append(bar + '⏰' + format_eta(remaining) +
                     (' ' + _render_projection(chip, theme, use_color) if chip else ''))
    return ' | '.join(parts)
