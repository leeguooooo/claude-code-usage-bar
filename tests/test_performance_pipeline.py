import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

from claude_statusbar import activity, daemon, git_cache, _git_refresh


def test_unchanged_transcript_keeps_clock_moving(tmp_path, monkeypatch):
    p = tmp_path / 'session.jsonl'
    now = datetime.now(timezone.utc)
    p.write_text(json.dumps({'type': 'assistant', 'timestamp': now.isoformat(),
        'message': {'content': [], 'usage': {}}}) + '\n')
    first = activity.read_activity(str(p), now)
    monkeypatch.setattr(activity, '_read_activity_uncached',
                        lambda *a: (_ for _ in ()).throw(AssertionError('rescanned')))
    next_info = activity.read_activity(str(p), now + timedelta(seconds=10))
    assert next_info.cache_age_seconds == first.cache_age_seconds + 10


def test_replaced_transcript_invalidates_snapshot(tmp_path):
    p = tmp_path / 'session'
    p.write_text('{}\n')
    activity.read_activity(str(p))
    q = tmp_path / 'replacement'
    q.write_text(json.dumps({'type': 'assistant', 'timestamp': datetime.now(timezone.utc).isoformat(),
                            'message': {'content': []}}))
    q.replace(p)
    assert activity.read_activity(str(p)).cache_age_seconds is not None


def test_git_singleflight_and_failure_cache(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path))
    lock = git_cache.try_claim('/repo')
    assert git_cache.try_claim('/repo') is None
    lock.close()
    monkeypatch.setattr(_git_refresh, '_git_executable', lambda: None)
    _git_refresh.refresh('/repo')
    assert git_cache.is_fresh(git_cache.read_cache('/repo'))
    assert git_cache.read_cache('/repo')['dirty'] is None


def test_scheduler_isolates_slow_session(tmp_path, monkeypatch):
    from claude_statusbar import render_scheduler as rs
    monkeypatch.setattr(daemon, '_cache_dir', lambda: tmp_path)
    monkeypatch.setattr(daemon, '_active_sessions', lambda: ['slow', 'fast'])
    for sid in ['slow', 'fast']:
        (tmp_path / sid).write_text(json.dumps({'sid': sid}))
    monkeypatch.setattr(daemon, 'session_stdin_path', lambda sid: tmp_path / sid)
    published = []
    monkeypatch.setattr(daemon, '_publish_render', lambda sid, *args: published.append(sid))
    real_popen = subprocess.Popen
    code = ('import sys,json,time\nfor line in sys.stdin:\n'
            ' p=json.loads(json.loads(line))\n'
            ' if p["sid"]=="slow": time.sleep(2)\n'
            ' print(json.dumps("bar"),flush=True)\n')
    monkeypatch.setattr(rs.subprocess, 'Popen',
        lambda args, **kw: real_popen([sys.executable, '-u', '-c', code], **kw))
    scheduler = rs.Scheduler()
    try:
        end = time.monotonic() + 1
        while time.monotonic() < end and 'fast' not in published:
            scheduler.tick(.1)
            time.sleep(.01)
        assert 'fast' in published
        assert 'slow' not in published
        assert len(scheduler.workers) == 2
        monkeypatch.setattr(daemon, 'RENDER_TIMEOUT_S', 0)
        end = time.monotonic() + 1.5
        while time.monotonic() < end and not scheduler.timeouts:
            scheduler.tick(.1)
            time.sleep(.01)
        assert scheduler.timeouts == 1
        assert scheduler.due['slow'] > time.monotonic()
    finally:
        scheduler.close()


def test_scoped_parser_and_opt_in():
    from claude_statusbar.scoped_usage import parse_limits, render_limits
    from claude_statusbar.config import StatusbarConfig
    from claude_statusbar.themes import get_theme
    assert not StatusbarConfig().show_per_model
    row = dict(kind='weekly_scoped', percent=81,
               resets_at=(datetime.now(timezone.utc) + timedelta(days=3)).isoformat(),
               scope={'model': {'display_name': 'Fable'}})
    limits = parse_limits({'limits': [row, None, {}, {**row, 'percent': float('nan')}]})
    assert len(limits) == 1
    text = render_limits(limits, get_theme('graphite'), False, 70, 90)
    assert 'Fable[' in text and '81%' in text and '→' in text


def test_cache_only_uses_explicit_session(tmp_path, monkeypatch):
    from claude_statusbar import core
    seen = []
    monkeypatch.setattr(core, '_last_assistant_info',
                        lambda p: (seen.append(p) or (1, 300)))
    core.get_cache_age_text(transcript_path='/current-session')
    assert seen == ['/current-session']


def test_scoped_auth_failure_is_cached(tmp_path, monkeypatch):
    from claude_statusbar import scoped_usage, predict
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setattr(predict, 'account_id', lambda: 'fixture-account')
    reads = []
    monkeypatch.setattr(scoped_usage, '_token', lambda: reads.append(True))
    scoped_usage.refresh('fixture-account')
    scoped_usage.refresh('fixture-account')
    assert reads == [True]
    assert scoped_usage.cached_limits(spawn=False) == []
    assert 'token' not in scoped_usage._path('fixture-account').read_text()


def test_scoped_account_switch_never_reuses_previous_account(tmp_path, monkeypatch):
    from claude_statusbar import scoped_usage, predict
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setattr(predict, 'account_id', lambda: 'new-account')
    monkeypatch.setattr(scoped_usage, '_token',
        lambda: (_ for _ in ()).throw(AssertionError('unexpected credential read')))
    scoped_usage.refresh('old-account')
    assert not scoped_usage._path('old-account').exists()
    assert scoped_usage.cached_limits(spawn=False) == []


def test_appended_partial_record_and_truncation(tmp_path):
    p = tmp_path/'log'
    p.write_bytes(b'{"type":"user"}\n{"type":')
    assert list(activity._iter_entries_reverse(str(p))) == [{'type':'user'}]
    with p.open('ab') as f:
        f.write(b'"assistant"}\n')
    assert list(activity._iter_entries_reverse(str(p)))[0] == {'type':'assistant'}
    p.write_bytes(b'{}\n')
    assert list(activity._iter_entries_reverse(str(p))) == [{}]


def test_scheduler_spawn_failure_is_throttled(tmp_path, monkeypatch):
    from claude_statusbar.render_scheduler import Scheduler
    monkeypatch.setattr(daemon, '_active_sessions', lambda: ['s'])
    monkeypatch.setattr(daemon, '_cache_dir', lambda: tmp_path)
    scheduler = Scheduler()
    calls = []
    def fail():
        calls.append(True)
        raise OSError('process limit')
    monkeypatch.setattr(scheduler, '_start', fail)
    for _ in range(20):
        scheduler.tick(1)
    assert calls == [True]
