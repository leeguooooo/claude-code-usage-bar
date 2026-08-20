import os
import subprocess
from pathlib import Path

from claude_statusbar.cleanup import _active_mei_dirs, cleanup_legacy_mei_dirs


def _legacy_dir(root: Path, name: str, *, mtime: float) -> Path:
    path = root / name
    path.mkdir()
    for child in ("AppKit", "CoreFoundation", "Foundation", "Python.framework"):
        (path / child).mkdir()
    (path / "Python.framework" / "Python").write_bytes(b"runtime")
    os.utime(path, (mtime, mtime))
    return path


def test_cleanup_removes_inactive_legacy_cohort(tmp_path):
    now = 10_000.0
    dirs = [
        _legacy_dir(tmp_path, f"_MEIabc12{i}", mtime=now - 1_000)
        for i in range(3)
    ]

    result = cleanup_legacy_mei_dirs(
        temp_root=tmp_path,
        now=now,
        active_dirs=set(),
        platform="darwin",
    )

    assert result.removed == 3
    assert result.bytes_freed == 3 * len(b"runtime")
    assert all(not path.exists() for path in dirs)


def test_cleanup_never_removes_active_or_fresh_directories(tmp_path):
    now = 10_000.0
    active = _legacy_dir(tmp_path, "_MEIactive1", mtime=now - 2_000)
    fresh = _legacy_dir(tmp_path, "_MEIfresh01", mtime=now - 10)
    stale = [
        _legacy_dir(tmp_path, f"_MEIstale{i}", mtime=now - 2_000)
        for i in range(3)
    ]

    result = cleanup_legacy_mei_dirs(
        temp_root=tmp_path,
        now=now,
        active_dirs={active},
        platform="darwin",
    )

    assert result.removed == 3
    assert result.skipped_active == 1
    assert active.exists()
    assert fresh.exists()
    assert all(not path.exists() for path in stale)


def test_cleanup_requires_a_cohort_and_signature(tmp_path):
    now = 10_000.0
    single = _legacy_dir(tmp_path, "_MEIsingle1", mtime=now - 2_000)
    unrelated = tmp_path / "_MEIother01"
    unrelated.mkdir()
    (unrelated / "some-other-app").write_text("keep", encoding="utf-8")
    os.utime(unrelated, (now - 2_000, now - 2_000))

    result = cleanup_legacy_mei_dirs(
        temp_root=tmp_path,
        now=now,
        active_dirs=set(),
        platform="darwin",
    )

    assert result.removed == 0
    assert single.exists()
    assert unrelated.exists()


def test_cleanup_aborts_when_open_file_inventory_fails(tmp_path, monkeypatch):
    now = 10_000.0
    dirs = [
        _legacy_dir(tmp_path, f"_MEIfail0{i}", mtime=now - 2_000)
        for i in range(3)
    ]
    monkeypatch.setattr("claude_statusbar.cleanup._active_mei_dirs", lambda _root: None)

    result = cleanup_legacy_mei_dirs(
        temp_root=tmp_path,
        now=now,
        platform="darwin",
    )

    assert result.removed == 0
    assert "open files" in result.reason
    assert all(path.exists() for path in dirs)


def test_cleanup_is_macos_only(tmp_path):
    result = cleanup_legacy_mei_dirs(
        temp_root=tmp_path,
        active_dirs=set(),
        platform="linux",
    )
    assert result.removed == 0
    assert result.reason == "not macOS"


def test_open_file_inventory_maps_nested_file_to_mei_root(tmp_path, monkeypatch):
    active = tmp_path / "_MEIactive1"
    nested = active / "Python.framework" / "Python"

    class Result:
        returncode = 0
        stdout = f"p123\nfcwd\nn{nested}\n"

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: Result())
    assert _active_mei_dirs(tmp_path) == {active}


def test_open_file_inventory_fails_closed_on_lsof_error(tmp_path, monkeypatch):
    class Result:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: Result())
    assert _active_mei_dirs(tmp_path) is None
