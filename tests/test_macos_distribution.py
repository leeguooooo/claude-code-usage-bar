"""Signing order, rejection gates and installer authenticity checks."""
import importlib.util
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('sign_macos', ROOT / 'scripts/sign_macos.py')
sign_macos = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sign_macos)


def test_signing_orders_embedded_code_before_framework_seals(tmp_path):
    framework = tmp_path / 'Python.framework'
    binary = framework / 'Versions/A/Python'
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b'\xcf\xfa\xed\xfe' + b'fixture')
    (tmp_path / 'plain.txt').write_text('not executable code')
    assert sign_macos.code_paths(tmp_path) == [binary, framework]


@pytest.mark.skipif(os.name == 'nt', reason='Mac bundle symlinks')
def test_signing_rejects_external_symlinks(tmp_path):
    root = tmp_path / 'bundle'
    root.mkdir()
    (root / 'external').symlink_to(tmp_path / 'private-material')
    with pytest.raises(ValueError, match='escapes'):
        sign_macos.code_paths(root)


def test_rejected_notarization_never_staples_or_reports_success(tmp_path, monkeypatch):
    monkeypatch.setattr(sign_macos.subprocess, 'run', lambda *a, **k:
                        SimpleNamespace(stdout=json.dumps({'status': 'Invalid'})))
    calls = []
    monkeypatch.setattr(sign_macos, 'run', lambda *a, **k: calls.append(a))
    with pytest.raises(RuntimeError, match='did not accept'):
        sign_macos.notarize(tmp_path / 'fixture.dmg', profile='fixture-profile')
    assert calls == []


def test_accepted_notarization_requires_staple_and_gatekeeper(tmp_path, monkeypatch):
    monkeypatch.setattr(sign_macos.subprocess, 'run', lambda *a, **k:
                        SimpleNamespace(stdout=json.dumps({'status': 'Accepted', 'id': 'fixture-id'})))
    calls = []
    monkeypatch.setattr(sign_macos, 'run', lambda *a, **k: calls.append(a))
    assert sign_macos.notarize(tmp_path / 'fixture.dmg', profile='fixture-profile') == 'fixture-id'
    assert [str(call[1]) for call in calls[:2]] == ['stapler', 'stapler']
    assert calls[0][2] == 'staple' and calls[1][2] == 'validate'
    assert calls[2][0] == 'spctl'


def test_installer_cannot_accept_missing_checksum(tmp_path):
    # Run the real function independently: no downloads, services or keychain.
    installer = (ROOT / 'install.sh').read_text()
    start = installer.index('verify_checksum() {')
    end = installer.index('\nverify_apple_signature()', start)
    code = installer[start:end]
    script = 'set -euo pipefail\nerr() { :; }\ncurl() { return 1; }\n' + code
    script += '\nverify_checksum "file:///fixture" "fixture.tar.gz" "$1"\n'
    if os.name == 'nt':
        pytest.skip('POSIX installer')
    result = subprocess.run(['bash', '-c', script, 'test', str(tmp_path)], capture_output=True)
    assert result.returncode != 0


def test_new_release_cannot_publish_without_notarized_disk_image():
    import release_plan
    info = {'assets': [{'name': name, 'state': 'uploaded', 'size': 100}
                       for name in release_plan.ASSETS], 'draft': False}
    assert not release_plan.plan(info, True, '3.45.1')['binaries']
    assert release_plan.plan(info, True, '3.46.0')['binaries']
    for name in ('cs-darwin-arm64.dmg', 'cs-darwin-arm64.dmg.sha256'):
        info['assets'].append({'name': name, 'state': 'uploaded', 'size': 100})
    assert not release_plan.plan(info, True, '3.46.0')['binaries']
