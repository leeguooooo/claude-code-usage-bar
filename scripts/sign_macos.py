"""Developer ID sign an onedir bundle and notarize its distributable DMG.

Credentials stay in the keychain or environment. This script never exports a
private key, changes keychain trust, or removes quarantine attributes.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MACHO_MAGICS = {b'\xfe\xed\xfa\xce', b'\xce\xfa\xed\xfe',
                b'\xfe\xed\xfa\xcf', b'\xcf\xfa\xed\xfe',
                b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca',
                b'\xca\xfe\xba\xbf', b'\xbf\xba\xfe\xca'}


def code_paths(bundle):
    """Sign nested code before the framework containers that seal it."""
    root = bundle.resolve()
    binaries, frameworks = [], []
    for path in bundle.rglob('*'):
        if path.is_symlink():
            if not path.resolve().is_relative_to(root):
                raise ValueError('bundle symlink escapes its root')
            continue
        if path.is_dir() and path.suffix == '.framework':
            frameworks.append(path)
        elif path.is_file():
            with path.open('rb') as source:
                if source.read(4) in MACHO_MAGICS:
                    binaries.append(path)
    return sorted(binaries, key=lambda p: len(p.parts), reverse=True) + sorted(
        frameworks, key=lambda p: len(p.parts), reverse=True)


def run(*args, **kwargs):
    subprocess.run(list(map(str, args)), check=True, **kwargs)


def sign(bundle, identity, keychain=None):
    paths = code_paths(bundle)
    if not paths or not (bundle / 'cs').is_file() or not (bundle / 'cs-python').is_file():
        raise ValueError('expected a native cs + onedir Python runtime bundle')
    for path in paths:
        args = ['codesign', '--force', '--options', 'runtime', '--timestamp', '--sign', identity]
        if keychain:
            args += ['--keychain', keychain]
        if path == bundle / 'cs':
            args += ['--identifier', 'com.leeguoo.claude-statusbar.cli']
        elif path == bundle / 'cs-python':
            args += ['--identifier', 'com.leeguoo.claude-statusbar.runtime']
        run(*args, path)
    for path in paths:
        run('codesign', '--verify', '--strict', path)
    for path in (bundle / 'cs', bundle / 'cs-python'):
        details = subprocess.run(['codesign', '--display', '--verbose=4', str(path)],
                                 capture_output=True, text=True, check=True).stderr
        if ('Authority=Developer ID Application:' not in details
                or 'TeamIdentifier=6ZPXG4KVVS' not in details
                or '(runtime)' not in details):
            raise ValueError('unexpected signing identity or missing hardened runtime')
    return len(paths)


def notarize(dmg, profile=None):
    args = ['xcrun', 'notarytool', 'submit', str(dmg), '--wait', '--timeout', '30m',
            '--output-format', 'json']
    if profile:
        args += ['--keychain-profile', profile]
    else:
        for name in ('ASC_KEY_PATH', 'ASC_KEY_ID', 'ASC_ISSUER_ID'):
            if not os.environ.get(name):
                raise ValueError('missing notarization configuration: ' + name)
        args += ['--key', os.environ['ASC_KEY_PATH'], '--key-id', os.environ['ASC_KEY_ID'],
                 '--issuer', os.environ['ASC_ISSUER_ID']]
    result = subprocess.run(args, capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    if data.get('status') != 'Accepted':
        raise RuntimeError('Apple notarization did not accept the DMG')
    run('xcrun', 'stapler', 'staple', dmg)
    run('xcrun', 'stapler', 'validate', dmg)
    run('spctl', '--assess', '--type', 'open', '--context', 'context:primary-signature', dmg)
    return data['id']


def package(bundle, output, identity, keychain=None, profile=None):
    output.mkdir(parents=True, exist_ok=True)
    count = sign(bundle, identity, keychain)
    run(bundle / 'cs', '--version')
    run(bundle / 'cs', 'hud', 'check')
    dmg = output / 'cs-darwin-arm64.dmg'
    with tempfile.TemporaryDirectory(prefix='cs-dmg-') as tmp:
        stage = Path(tmp)
        shutil.copytree(bundle, stage / 'cs', symlinks=True)
        (stage / 'Install.txt').write_text(
            'Claude Status Bar\n\nInstall or upgrade without sudo:\n'
            'curl -fsSL https://raw.githubusercontent.com/leeguooooo/claude-code-usage-bar/main/install.sh | bash\n'
            '\nThis disk image includes the signed CLI, Python runtime and desktop HUD.\n',
            encoding='utf-8')
        run('hdiutil', 'create', '-volname', 'Claude Status Bar', '-srcfolder', stage,
            '-ov', '-format', 'UDZO', dmg, stdout=subprocess.DEVNULL)
    args = ['codesign', '--force', '--timestamp', '--sign', identity]
    if keychain:
        args += ['--keychain', keychain]
    run(*args, dmg)
    submission = notarize(dmg, profile)
    # Tar remains available for existing clients; these exact binary hashes
    # were scanned inside the notarized DMG. Only the DMG can carry a ticket.
    archive = output / 'cs-darwin-arm64.tar.gz'
    run('tar', '-czf', archive, '-C', bundle.parent, bundle.name)
    for path in (dmg, archive):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        path.with_name(path.name + '.sha256').write_text(f'{digest}  {path.name}\n')
    print(json.dumps({'signed_code_objects': count, 'notarization': 'Accepted',
                      'submission_id': submission, 'dmg': str(dmg)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--identity', default=os.environ.get('SIGNING_IDENTITY', 'Developer ID Application'))
    parser.add_argument('--keychain', default=os.environ.get('SIGNING_KEYCHAIN'))
    parser.add_argument('--profile', default=os.environ.get('NOTARY_KEYCHAIN_PROFILE'))
    args = parser.parse_args()
    if sys.platform != 'darwin':
        raise SystemExit('macOS signing requires a Mac')
    package(args.bundle.resolve(), args.output.resolve(), args.identity, args.keychain, args.profile)


if __name__ == '__main__':
    main()
