"""Verify all binary sidecars before making a draft release public."""
import argparse
import hashlib
import os
import subprocess
import tempfile
from pathlib import Path

from release_plan import ASSETS, release_info


def verify(directory):
    for name in ASSETS:
        if not (directory / name).is_file() or not (directory / name).stat().st_size:
            raise ValueError('missing release asset: ' + name)
    for name in ASSETS:
        if name.endswith('.sha256'):
            continue
        tokens = (directory / (name + '.sha256')).read_text().split()
        if len(tokens) != 2 or tokens[1].lstrip('*') != name:
            raise ValueError('invalid checksum sidecar: ' + name)
        with (directory / name).open('rb') as source:
            digest = hashlib.sha256()
            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(chunk)
        if tokens[0] != digest.hexdigest():
            raise ValueError('checksum mismatch: ' + name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('tag')
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    repo = os.environ['GITHUB_REPOSITORY']
    release = release_info(repo, args.tag)
    if release is None:
        raise SystemExit('release is missing or draft access is unavailable')
    assets = {asset['name']: asset for asset in release['assets']}
    with tempfile.TemporaryDirectory() as tmp:
        for name in ASSETS:
            asset = assets.get(name)
            if asset is None:
                raise SystemExit('missing release asset: ' + name)
            with (Path(tmp) / name).open('wb') as output:
                subprocess.run(['gh', 'api', f'repos/{repo}/releases/assets/{asset["id"]}',
                                '-H', 'Accept: application/octet-stream'], stdout=output, check=True)
        verify(Path(tmp))
    if args.publish:
        subprocess.run(['gh', 'api', '--method', 'PATCH',
                        f'repos/{repo}/releases/{release["id"]}',
                        '-F', 'draft=false', '-f', 'make_latest=true'],
                       stdout=subprocess.DEVNULL, check=True)


if __name__ == '__main__':
    main()
