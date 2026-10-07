"""Verify all binary sidecars before making a draft release public."""
import argparse
import hashlib
import subprocess
import tempfile
from pathlib import Path

from release_plan import ASSETS


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
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(['gh', 'release', 'download', args.tag, '--dir', tmp,
                        '--pattern', 'cs-*.tar.gz*'], check=True)
        verify(Path(tmp))


if __name__ == '__main__':
    main()
