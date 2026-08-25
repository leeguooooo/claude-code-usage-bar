"""Upgrades must replace docs we installed, and only keep what the user wrote.

Regression: `install_skills` compared the file on disk to the *currently
bundled* copy, so shipping a newer SKILL.md looked identical to a user edit.
Every doc froze at whatever version was installed first — one install sat at
v3.5.0 for 29 releases while the installer insisted, each time, that it was
preserving the user's edit.
"""
import json

import pytest

from claude_statusbar import setup as setup_mod


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    src = tmp_path / "pkg" / "commands"
    src.mkdir(parents=True)
    dst_dir = tmp_path / "home" / "commands"
    monkeypatch.setattr(setup_mod, "COMMANDS_DIR", dst_dir)
    monkeypatch.setattr(setup_mod, "_packaged_commands_dir", lambda: src)
    monkeypatch.setattr(setup_mod, "INSTALLED_DOCS_MANIFEST",
                        tmp_path / "manifest.json")
    return src, dst_dir


def test_first_install_writes_and_records(sandbox):
    src, dst_dir = sandbox
    (src / "a.md").write_text("v1\n")

    n, skipped, failed = setup_mod.install_commands()

    assert (n, skipped, failed) == (1, [], [])
    assert (dst_dir / "a.md").read_text() == "v1\n"
    assert str(dst_dir / "a.md") in json.loads(
        setup_mod.INSTALLED_DOCS_MANIFEST.read_text())


def test_our_own_untouched_file_is_upgraded(sandbox):
    src, dst_dir = sandbox
    (src / "a.md").write_text("v1\n")
    setup_mod.install_commands()

    (src / "a.md").write_text("v2 — new docs\n")   # we ship a newer version
    n, skipped, failed = setup_mod.install_commands()

    assert skipped == [] and failed == []
    assert (dst_dir / "a.md").read_text() == "v2 — new docs\n"


def test_user_edit_is_kept(sandbox):
    src, dst_dir = sandbox
    (src / "a.md").write_text("v1\n")
    setup_mod.install_commands()
    (dst_dir / "a.md").write_text("my own notes\n")

    (src / "a.md").write_text("v2\n")
    n, skipped, failed = setup_mod.install_commands()

    assert skipped == [str(dst_dir / "a.md")]
    assert (dst_dir / "a.md").read_text() == "my own notes\n"


def test_unknown_provenance_is_kept_not_clobbered(sandbox):
    # Files installed before the manifest existed: we can't prove they're ours,
    # so we keep them — but the message says so instead of blaming the user.
    src, dst_dir = sandbox
    dst_dir.mkdir(parents=True)
    (dst_dir / "a.md").write_text("installed by an old release\n")
    (src / "a.md").write_text("v2\n")

    n, skipped, failed = setup_mod.install_commands()

    assert skipped == [str(dst_dir / "a.md")]
    assert (dst_dir / "a.md").read_text() == "installed by an old release\n"


def test_force_overwrites_even_a_user_edit(sandbox):
    src, dst_dir = sandbox
    (src / "a.md").write_text("v1\n")
    setup_mod.install_commands()
    (dst_dir / "a.md").write_text("mine\n")
    (src / "a.md").write_text("v2\n")

    n, skipped, failed = setup_mod.install_commands(force=True)

    assert (n, skipped, failed) == (1, [], [])
    assert (dst_dir / "a.md").read_text() == "v2\n"


def test_edit_then_revert_to_ours_is_upgraded_again(sandbox):
    # The user edits, then puts our content back. That's ours again.
    src, dst_dir = sandbox
    (src / "a.md").write_text("v1\n")
    setup_mod.install_commands()
    (dst_dir / "a.md").write_text("scribble\n")
    (dst_dir / "a.md").write_text("v1\n")

    (src / "a.md").write_text("v2\n")
    setup_mod.install_commands()

    assert (dst_dir / "a.md").read_text() == "v2\n"
