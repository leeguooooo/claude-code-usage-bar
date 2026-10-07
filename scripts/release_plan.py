"""Plan missing release work without treating an existing tag as completion."""
import argparse
import json
import os
import re
import subprocess
import urllib.error
import urllib.request

import release_meta

ASSETS = tuple(name + suffix for name in
               ('cs-darwin-arm64.tar.gz', 'cs-linux-x86_64.tar.gz')
               for suffix in ('', '.sha256'))


def required_assets(version=None):
    if version and tuple(map(int, version.split('.'))) >= (3, 46, 0):
        return ASSETS + ('cs-darwin-arm64.dmg', 'cs-darwin-arm64.dmg.sha256')
    return ASSETS


def plan(release, pypi_present, version=None):
    names = {asset['name'] for asset in (release or {}).get('assets', [])
             if asset.get('state') == 'uploaded' and asset.get('size', 0) > 0}
    binaries = not set(required_assets(version)) <= names
    publish = release is None or release.get('draft', False)
    return {'release': binaries or publish or not pypi_present,
            'binaries': binaries, 'pypi': not pypi_present,
            'draft': publish}


def release_info(repo, tag):
    result = subprocess.run(['gh', 'api', f'repos/{repo}/releases/tags/{tag}'],
                            capture_output=True, text=True, check=False)
    if result.returncode:
        if 'HTTP 404' in result.stderr:
            return None
        raise RuntimeError('GitHub release lookup failed')
    return json.loads(result.stdout)


def pypi_has_version(version):
    try:
        with urllib.request.urlopen(
                f'https://pypi.org/pypi/claude-statusbar/{version}/json', timeout=15) as response:
            data = json.load(response)
        kinds = {row.get('packagetype') for row in data.get('urls', [])}
        return {'bdist_wheel', 'sdist'} <= kinds
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return False
        raise


def git_text(ref, path):
    return subprocess.check_output(['git', 'show', f'{ref}:{path}'], text=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('version')
    args = parser.parse_args()
    version = args.version
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise SystemExit('release version must be X.Y.Z')
    tag = 'v' + version
    existing = subprocess.run(['git', 'rev-parse', '-q', '--verify', f'refs/tags/{tag}'],
                              capture_output=True, text=True, check=False)
    ref = tag if existing.returncode == 0 else os.environ['GITHUB_SHA']
    if release_meta.pyproject_version(git_text(ref, 'pyproject.toml')) != version:
        raise SystemExit('source version does not match requested release')
    for path in ('.claude-plugin/plugin.json', '.claude-plugin/marketplace.json'):
        if release_meta._plugin_version(json.loads(git_text(ref, path))) != version:
            raise SystemExit('plugin version drift')
    notes = release_meta.changelog_section(version, git_text(ref, 'CHANGELOG.md'))
    result = plan(release_info(os.environ['GITHUB_REPOSITORY'], tag), pypi_has_version(version), version)
    result.update(version=version, tag=tag, ref=ref,
                  title=release_meta.title(version, notes))
    with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
        for key, value in result.items():
            output.write(f'{key}={str(value).lower() if isinstance(value, bool) else value}\n')


if __name__ == '__main__':
    main()
