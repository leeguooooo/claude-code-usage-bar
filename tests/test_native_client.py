"""Test the compiled entrypoint, not imported Python hot-path functions."""
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest


@pytest.fixture(scope='module')
def native(tmp_path_factory):
    if not shutil.which('go') or os.name == 'nt':
        pytest.skip('POSIX Go compiler required')
    root = tmp_path_factory.mktemp('native')
    subprocess.run(['go', 'build', '-o', str(root / 'cs'),
                    'packaging/native/main.go'], check=True, timeout=90)
    runtime = root / 'cs-python'
    runtime.write_text('#!/bin/sh\nprintf "fallback:"\ncat\n')
    runtime.chmod(0o755)
    return root / 'cs'


def setup_cache(tmp_path, sid='s', **extra):
    root = tmp_path / '.cache' / 'claude-statusbar'
    p = root / 'sessions' / sid
    p.mkdir(parents=True, exist_ok=True)
    (p / 'rendered.ansi').write_text('CURRENT\n')
    m = dict(generated_at=time.time(), daemon_started_at=time.time()+1,
             stale_after_seconds=5, native_protocol=1, columns='', pid=os.getpid())
    m.update(extra)
    (p / 'rendered.meta.json').write_text(json.dumps(m))
    return p


def invoke(native, tmp_path, payload, **env):
    return subprocess.run([str(native), 'render'], input=json.dumps(payload),
        env={**os.environ, 'HOME': str(tmp_path), 'COLUMNS': '', **env},
        capture_output=True, text=True, timeout=5)


def test_cache_hit_never_starts_runtime(native, tmp_path):
    p = setup_cache(tmp_path)
    result = invoke(native, tmp_path, {'session_id':'s'}, CS_API_MODE='on')
    assert result.returncode == 0 and result.stdout == 'CURRENT\n'
    assert json.loads((p / 'last_stdin.json').read_text())['_cs_env']['CS_API_MODE'] == 'on'


@pytest.mark.parametrize('change', [dict(native_protocol=0), dict(columns='20'),
    dict(generated_at=0), dict(daemon_started_at=0), dict(generated_at=time.time()+100)])
def test_incompatible_cache_delegates_with_original_input(native, tmp_path, change):
    setup_cache(tmp_path, **change)
    payload = {'session_id':'s', 'model':{'id':'original'}}
    result = invoke(native, tmp_path, payload)
    assert result.stdout.startswith('fallback:')
    assert json.loads(result.stdout[len('fallback:'):]) == payload


def test_native_does_not_wait_for_eof(native, tmp_path):
    setup_cache(tmp_path)
    p = subprocess.Popen([str(native), 'render'], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, env={**os.environ, 'HOME':str(tmp_path), 'COLUMNS':''})
    try:
        p.stdin.write(b'{"session_id":"s"}')
        p.stdin.flush()
        assert p.wait(timeout=3) == 0
        assert p.stdout.read() == b'CURRENT\n'
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()
        p.stdin.close()
        p.stdout.close()


def test_native_session_isolation(native, tmp_path):
    setup_cache(tmp_path, 'a')
    p = setup_cache(tmp_path, 'b')
    (p/'rendered.ansi').write_text('SECOND\n')
    assert invoke(native, tmp_path, {'session_id':'b'}).stdout == 'SECOND\n'
    assert invoke(native, tmp_path, {'session_id':'a'}).stdout == 'CURRENT\n'


def test_native_cold_start_budget(native, tmp_path):
    import fcntl
    root = tmp_path/'.cache'/'claude-statusbar'
    root.mkdir(parents=True)
    slots = [open(root/f'native.bootstrap.{i}', 'a+b') for i in range(2)]
    try:
        for slot in slots:
            fcntl.flock(slot, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert invoke(native, tmp_path, {'session_id':'cold'}).stdout == 'cs: warming up…\n'
    finally:
        for slot in slots:
            slot.close()
    assert invoke(native, tmp_path, {'session_id':'cold'}).stdout.startswith('fallback:')
