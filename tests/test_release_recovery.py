"""Offline release state transitions and artifact verification."""
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


load('release_meta')
release_plan = load('release_plan')
verify_assets = load('verify_release_assets')


def release(draft=False, names=None):
    return {'draft': draft, 'assets': [{'name': name, 'state': 'uploaded', 'size': 100}
                                     for name in (release_plan.ASSETS if names is None else names)]}


@pytest.mark.parametrize('info,pypi,expected', [
    (None, False, (True, True, True, True)),
    (release(), True, (False, False, False, False)),
    (release(draft=True), True, (True, False, False, True)),
    (release(names=release_plan.ASSETS[:2]), True, (True, True, False, False)),
    (release(), False, (True, False, True, False)),
    (release(draft=True, names=[]), True, (True, True, False, True)),
])
def test_only_missing_work_is_retried(info, pypi, expected):
    plan = release_plan.plan(info, pypi)
    assert tuple(plan[k] for k in ('release', 'binaries', 'pypi', 'draft')) == expected


def test_uploaded_empty_assets_do_not_count_as_complete():
    info = release()
    info['assets'][0]['size'] = 0
    assert release_plan.plan(info, True)['binaries']


def test_auth_failure_does_not_masquerade_as_missing_release(monkeypatch):
    monkeypatch.setattr(release_plan.subprocess, 'run', lambda *a, **k:
                        SimpleNamespace(returncode=1, stderr='HTTP 401', stdout=''))
    with pytest.raises(RuntimeError):
        release_plan.release_info('owner/repo', 'v1.0.0')


def test_missing_public_release_is_planned_as_staged_work(monkeypatch):
    monkeypatch.setattr(release_plan.subprocess, 'run', lambda *a, **k:
                        SimpleNamespace(returncode=1, stderr='HTTP 404', stdout=''))
    assert release_plan.release_info('owner/repo', 'v1.0.0') is None
    assert release_plan.plan(None, True)['binaries']


def test_existing_tag_supplies_version_and_notes_on_recovery(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['release_plan.py', '1.0.0'])
    monkeypatch.setenv('GITHUB_OUTPUT', str(tmp_path / 'outputs'))
    monkeypatch.setenv('GITHUB_REPOSITORY', 'owner/repo')
    monkeypatch.setenv('GITHUB_SHA', 'newer-main-sha')
    monkeypatch.setattr(release_plan.subprocess, 'run', lambda *a, **k:
                        SimpleNamespace(returncode=0, stderr='', stdout='old-sha'))
    refs = []
    def git_text(ref, path):
        refs.append(ref)
        if path == 'pyproject.toml':
            return '[project]\nversion = "1.0.0"\n'
        if path == 'CHANGELOG.md':
            return '## v1.0.0\n\n**Original release.**\n'
        return json.dumps({'version': '1.0.0'})
    monkeypatch.setattr(release_plan, 'git_text', git_text)
    monkeypatch.setattr(release_plan, 'release_info', lambda *a: release(draft=True))
    monkeypatch.setattr(release_plan, 'pypi_has_version', lambda *a: True)
    release_plan.main()
    assert set(refs) == {'v1.0.0'}
    output = (tmp_path / 'outputs').read_text()
    assert 'ref=v1.0.0' in output and 'binaries=false' in output and 'draft=true' in output


def fixtures(directory):
    for name in release_plan.ASSETS:
        if name.endswith('.sha256'):
            continue
        data = b'synthetic bundle'
        (directory / name).write_bytes(data)
        (directory / (name + '.sha256')).write_text(hashlib.sha256(data).hexdigest() + '  ' + name)


def test_complete_assets_are_verified(tmp_path):
    fixtures(tmp_path)
    verify_assets.verify(tmp_path)


@pytest.mark.parametrize('damage', ['missing', 'corrupt', 'wrong-name'])
def test_bad_assets_block_publication(tmp_path, damage):
    fixtures(tmp_path)
    name = release_plan.ASSETS[0]
    if damage == 'missing':
        (tmp_path / name).unlink()
    elif damage == 'corrupt':
        (tmp_path / name).write_bytes(b'corrupt')
    else:
        (tmp_path / (name + '.sha256')).write_text('abc  wrong-name.tar.gz')
    with pytest.raises(ValueError):
        verify_assets.verify(tmp_path)


@pytest.mark.skipif(os.name == 'nt' or not shutil.which('bash'), reason='Linux workflow shell')
def test_workflow_creates_tag_before_building_and_never_moves_it(tmp_path):
    remote = tmp_path / 'remote.git'
    checkout = tmp_path / 'checkout'
    subprocess.run(['git', 'init', '--bare', '-q', str(remote)], check=True)
    subprocess.run(['git', 'init', '-q', str(checkout)], check=True)
    def git(*args):
        return subprocess.check_output(['git', '-C', str(checkout), *args], text=True).strip()
    git('remote', 'add', 'origin', str(remote))
    file = checkout / 'fixture'
    file.write_text('first')
    git('add', 'fixture')
    git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture')
    original = git('rev-parse', 'HEAD')
    workflow = (SCRIPTS.parent / '.github/workflows/release.yml').read_text()
    step = workflow.split('      - name: Ensure immutable tag exists', 1)[1]
    block = []
    for line in step.split('        run: |\n', 1)[1].splitlines():
        if line.strip() and not line.startswith('          '):
            break
        block.append(line)
    script = textwrap.dedent('\n'.join(block))
    env = {**os.environ, 'TAG': 'v1.0.0'}
    for _ in range(2):
        result = subprocess.run(['bash', '-c', script], cwd=checkout, env=env,
                                capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
    assert git('rev-parse', 'v1.0.0') == original
    file.write_text('newer main')
    git('add', 'fixture')
    git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'newer')
    result = subprocess.run(['bash', '-c', script], cwd=checkout, env=env,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert git('rev-parse', 'v1.0.0') == original
