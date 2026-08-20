"""Offline acceptance test for the release archive and atomic install layout."""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def _asset_name() -> str:
    system = platform.system()
    machine = platform.machine()
    if system == "Darwin" and machine in ("arm64", "aarch64"):
        return "cs-darwin-arm64.tar.gz"
    if system == "Linux" and machine in ("x86_64", "amd64"):
        return "cs-linux-x86_64.tar.gz"
    pytest.skip(f"installer test unsupported on {system}/{machine}")


def _write_release(release_dir: Path, version: str) -> str:
    source = release_dir / "source" / "cs"
    source.mkdir(parents=True, exist_ok=True)
    binary = source / "cs"
    binary.write_text(
        "#!/bin/sh\n"
        f"if [ \"${{1:-}}\" = --version ]; then echo 'cs {version}'; fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    binary.chmod(0o755)
    (source / "_internal").mkdir()
    (source / "_internal" / "runtime-marker").write_text("ok\n", encoding="utf-8")

    asset = release_dir / _asset_name()
    with tarfile.open(asset, "w:gz") as archive:
        archive.add(source, arcname="cs")
    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    (release_dir / f"{asset.name}.sha256").write_text(
        f"{digest}  {asset.name}\n", encoding="utf-8"
    )
    return hashlib.sha256(binary.read_bytes()).hexdigest()[:12]


def _run_installer(tmp_path: Path, release_dir: Path) -> subprocess.CompletedProcess:
    home = tmp_path / "home"
    install_dir = home / ".local" / "bin"
    bundle_root = home / ".local" / "lib" / "claude-statusbar"
    install_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "CS_INSTALL_DIR": str(install_dir),
            "CS_BUNDLE_ROOT": str(bundle_root),
            "CS_RELEASE_BASE_URL": release_dir.as_uri(),
            "PATH": f"{install_dir}:{env.get('PATH', '')}",
        }
    )
    return subprocess.run(
        ["bash", str(REPO_ROOT / "install.sh")],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        check=False,
    )


def test_installer_atomically_switches_onedir_and_prunes_old_version(tmp_path):
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    first_id = _write_release(release_dir, "9.8.7")

    first = _run_installer(tmp_path, release_dir)
    assert first.returncode == 0, first.stdout + first.stderr

    home = tmp_path / "home"
    install_dir = home / ".local" / "bin"
    bundle_root = home / ".local" / "lib" / "claude-statusbar"
    first_bundle = bundle_root / f"v9.8.7-{first_id}"
    assert first_bundle.is_dir()
    assert (first_bundle / "_internal" / "runtime-marker").is_file()
    assert (install_dir / "cs").is_symlink()
    assert (bundle_root / "current").resolve() == first_bundle.resolve()
    assert (install_dir / "cs").resolve() == (first_bundle / "cs").resolve()

    # Publish a second version at the same latest-release URL. The installer
    # switches `current` first, starts setup successfully, then removes the old
    # version directory so upgrades do not trade `_MEI` leaks for bundle leaks.
    for child in (release_dir / "source").iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    second_id = _write_release(release_dir, "9.8.8")
    second = _run_installer(tmp_path, release_dir)
    assert second.returncode == 0, second.stdout + second.stderr

    second_bundle = bundle_root / f"v9.8.8-{second_id}"
    assert (bundle_root / "current").resolve() == second_bundle.resolve(), (
        second.stdout + second.stderr
    )
    assert (install_dir / "cs").resolve() == (second_bundle / "cs").resolve()
    assert not first_bundle.exists()
