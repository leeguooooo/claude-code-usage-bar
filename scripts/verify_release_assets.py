"""Verify all staged binary sidecars before publishing a release."""
import argparse
import hashlib
from pathlib import Path

from release_plan import required_assets


def verify(directory, version=None):
    assets = required_assets(version)
    for name in assets:
        if not (directory / name).is_file() or not (directory / name).stat().st_size:
            raise ValueError('missing release asset: ' + name)
    for name in assets:
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
    parser.add_argument('--directory', required=True, type=Path)
    parser.add_argument('--version')
    args = parser.parse_args()
    verify(args.directory, args.version)


if __name__ == '__main__':
    main()
