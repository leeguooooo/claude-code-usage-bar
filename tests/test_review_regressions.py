"""Account boundaries, real concurrent writers and secret-free daemon inputs."""
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from claude_statusbar import balance_cache, cache, core, predict, quota_cache, render_thin
from claude_statusbar import _balance_refresh as refresh


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.setattr(balance_cache, '_cache_root', lambda: tmp_path / 'balance')
    return tmp_path


def parse(monkeypatch, data):
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps(data)))
    return core.parse_stdin_data()


def test_global_debug_payload_never_supplies_other_accounts_quota(sandbox, monkeypatch):
    path = sandbox / '.cache' / 'claude-statusbar' / 'last_stdin.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'rate_limits': {'five_hour': {
        'used_percentage': 91, 'resets_at': time.time() + 3600}}}))
    monkeypatch.setattr(predict, 'account_id', lambda *a: 'account-A')
    parse(monkeypatch, {'session_id': 'A', 'rate_limits': {'five_hour': {
        'used_percentage': 91, 'resets_at': time.time() + 3600}}})
    monkeypatch.setattr(predict, 'account_id', lambda *a: 'account-B')
    result = parse(monkeypatch, {'session_id': 'B'})
    assert result.get('rate_limit_pct') is None
    assert result.get('rate_limit_resets_at') is None


def test_unknown_accounts_only_reuse_their_own_session(sandbox, monkeypatch):
    data = {'session_id': 'A', 'rate_limits': {'five_hour': {
        'used_percentage': 42, 'resets_at': time.time() + 3600}}}
    parse(monkeypatch, data)
    assert parse(monkeypatch, {'session_id': 'A'})['rate_limit_pct'] == 42
    assert parse(monkeypatch, {'session_id': 'B'}).get('rate_limit_pct') is None
    assert parse(monkeypatch, {}).get('rate_limit_pct') is None


def test_identical_quota_is_not_rewritten_or_fsynced(sandbox, monkeypatch):
    calls = []
    original = cache.atomic_write_text
    def write(path, text, **kwargs):
        calls.append(kwargs)
        return original(path, text, **kwargs)
    monkeypatch.setattr(cache, 'atomic_write_text', write)
    data = {'session_id': 'A', 'rate_limits': {'five_hour': {
        'used_percentage': 42, 'resets_at': time.time() + 3600}}}
    parse(monkeypatch, data)
    parse(monkeypatch, data)
    assert calls == [{'durable': False}]
    assert 'session_id' not in json.loads(quota_cache.path_for(data).read_text())


def test_transaction_contention_has_a_deadline(tmp_path):
    path = tmp_path / 'quota'
    with cache.file_transaction(path):
        start = time.monotonic()
        with pytest.raises(TimeoutError):
            with cache.file_transaction(path, timeout=.03):
                pytest.fail('second writer acquired the lock')
        assert time.monotonic() - start < .5
    with cache.file_transaction(path):
        pass


def test_real_processes_preserve_high_quota_and_both_sessions(tmp_path):
    path = tmp_path / 'latest.json'
    marker = tmp_path / 'writer-ready'
    code = '''
import sys,time,json
from pathlib import Path
from claude_statusbar import predict,cache
path,marker,used=Path(sys.argv[1]),Path(sys.argv[2]),int(sys.argv[3])
original=cache.atomic_write_text
def write(path,text,**kwargs):
    if used==90:
        marker.write_text('ready')
        time.sleep(.25)
    return original(path,text,**kwargs)
cache.atomic_write_text=write
now=int(sys.argv[4])
out=predict.reconcile_account(used,now+3600,None,None,path=path,now=now,session_id=str(used))
assert out[0]==90,out
'''
    now = int(time.time())
    env = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')}
    first = subprocess.Popen([sys.executable, '-c', code, str(path), str(marker), '90', str(now)],
                             env=env, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(.005)
        assert marker.exists()
        second = subprocess.run([sys.executable, '-c', code, str(path), str(marker), '10', str(now)],
                                env=env, capture_output=True, timeout=5)
        assert second.returncode == 0, second.stderr
        assert first.wait(timeout=5) == 0, first.stderr.read()
        store = json.loads(path.read_text())
        assert store['five_hour'][str(now + 3600)]['used'] == 90
        assert set(store['sessions']) == {'90', '10'}
    finally:
        if first.poll() is None:
            first.kill()
            first.wait()
        first.stderr.close()


def test_balance_survives_session_injection_without_saving_credentials(sandbox, monkeypatch):
    env = {'ANTHROPIC_BASE_URL': 'https://relay.example',
           'ANTHROPIC_API_KEY': 'synthetic-primary', 'ANTHROPIC_AUTH_TOKEN': 'synthetic-fallback'}
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    fp = balance_cache.fingerprint(env['ANTHROPIC_BASE_URL'], env['ANTHROPIC_API_KEY'])
    balance_cache.write_cache_atomic(fp, {'ts': time.time(), 'supported': True,
                                        'balance': 25, 'total': 50})
    stamped = render_thin._inject_session_env(b'{"session_id":"fixture"}')
    session_env = json.loads(stamped)['_cs_env']
    assert core.relay_balance_text(env) == core.relay_balance_text(session_env) == 'bal $25.00'
    assert b'synthetic-primary' not in stamped and b'synthetic-fallback' not in stamped


def test_failed_usage_keeps_last_balance_with_a_stale_mark(sandbox, monkeypatch):
    fp = balance_cache.fingerprint('https://relay.example', 'synthetic')
    before = time.time() - 600
    balance_cache.write_cache_atomic(fp, {'ts': before, 'supported': True, 'balance': 25, 'total': 50})
    monkeypatch.setattr(refresh, '_probe', lambda *a: None)
    refresh._refresh_locked('https://relay.example', 'synthetic', '', fp)
    entry = balance_cache.read_cache(fp)
    assert entry['balance'] == 25 and entry['ts'] == before
    assert core._format_balance(entry) == 'bal $25.00 ⟳'
    assert balance_cache.is_fresh(entry)
    assert not balance_cache.is_fresh(entry, now=entry['attempted_at'] + 31)


@pytest.mark.parametrize('usage', [None, {}, {'total_usage': float('nan')},
                                 {'total_usage': float('inf')}, {'total_usage': -1}])
def test_unknown_usage_never_becomes_full_balance(monkeypatch, usage):
    monkeypatch.setattr(refresh, '_get_json',
                        lambda url, token: {'hard_limit_usd': 50} if url.endswith('/subscription') else usage)
    assert refresh._probe('https://relay.example', 'synthetic') is None
