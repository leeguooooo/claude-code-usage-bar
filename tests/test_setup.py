"""Tests for the install / repair flow.

Setup is the most fragile module — first-install reliability lives or dies
here. Use monkeypatching to redirect SETTINGS_PATH and COMMANDS_DIR into a
tmp dir so tests can never touch the real ~/.claude.
"""

import json
from pathlib import Path

import pytest

from claude_statusbar import setup as setup_mod


@pytest.fixture
def isolated(monkeypatch, tmp_path: Path):
    """Redirect setup module's paths into tmp_path."""
    settings = tmp_path / ".claude" / "settings.json"
    commands = tmp_path / ".claude" / "commands"
    monkeypatch.setattr(setup_mod, "SETTINGS_PATH", settings)
    monkeypatch.setattr(setup_mod, "COMMANDS_DIR", commands)
    return tmp_path, settings, commands


# ---------------------------------------------------------------------------
# _is_our_statusline
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("entry,expected", [
    ({"type": "command", "command": "cs"}, True),
    ({"type": "command", "command": "cstatus"}, True),
    ({"type": "command", "command": "claude-statusbar"}, True),
    ({"type": "command", "command": "/usr/local/bin/cs"}, True),
    ({"type": "command", "command": "/Users/foo/.local/bin/cstatus"}, True),
    ({"type": "command", "command": "starship"}, False),
    ({"type": "command", "command": "tmux-status"}, False),
    ({}, False),
    ("string-not-dict", False),
    (None, False),
])
def test_is_our_statusline(entry, expected):
    assert setup_mod._is_our_statusline(entry) is expected


# ---------------------------------------------------------------------------
# ensure_statusline_configured
# ---------------------------------------------------------------------------
def test_creates_statusline_when_missing(isolated):
    _, settings, _ = isolated
    changed, msg = setup_mod.ensure_statusline_configured()
    assert changed is True
    assert "Added" in msg
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["statusLine"]["type"] == "command"
    assert Path(data["statusLine"]["command"]).name in setup_mod.OUR_COMMAND_NAMES


def test_idempotent_when_already_configured(isolated):
    _, settings, _ = isolated
    setup_mod.ensure_statusline_configured()
    changed, msg = setup_mod.ensure_statusline_configured()
    assert changed is False
    assert msg == "statusLine already configured"


def test_does_not_overwrite_foreign_statusline(isolated):
    _, settings, _ = isolated
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps({
        "statusLine": {"type": "command", "command": "starship"}
    }) + "\n", encoding="utf-8")

    changed, msg = setup_mod.ensure_statusline_configured()
    assert changed is False
    assert "different statusLine command" in msg
    # Foreign config preserved
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["statusLine"]["command"] == "starship"


def test_refreshes_stale_path(isolated, monkeypatch):
    """When the existing entry is ours but the path is stale (e.g. user
    moved their venv), refresh it to the current resolved path."""
    _, settings, _ = isolated
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps({
        "statusLine": {"type": "command", "command": "/old/and/missing/cs"}
    }) + "\n", encoding="utf-8")

    monkeypatch.setattr(setup_mod, "_resolve_cs_command", lambda: "/new/path/cs")
    changed, msg = setup_mod.ensure_statusline_configured()
    assert changed is True
    assert "Refreshed" in msg
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["statusLine"]["command"] == "/new/path/cs"


def test_preserves_other_settings_keys(isolated):
    _, settings, _ = isolated
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps({
        "theme": "dark",
        "permissions": {"foo": "bar"},
    }) + "\n", encoding="utf-8")

    setup_mod.ensure_statusline_configured()
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["theme"] == "dark"
    assert data["permissions"] == {"foo": "bar"}
    assert "statusLine" in data


def test_handles_corrupt_settings_json(isolated):
    """If settings.json is corrupt, we treat it as empty rather than crash."""
    _, settings, _ = isolated
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text("{ this is not json", encoding="utf-8")

    changed, msg = setup_mod.ensure_statusline_configured()
    # We should still write a fresh config.
    assert changed is True
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert "statusLine" in data


# ---------------------------------------------------------------------------
# atomic write
# ---------------------------------------------------------------------------
def test_write_is_atomic_no_temp_files_left(isolated):
    _, settings, _ = isolated
    setup_mod.ensure_statusline_configured()
    leftover = list(settings.parent.glob(".settings.*.tmp"))
    assert leftover == [], f"temp files leaked: {leftover}"


# ---------------------------------------------------------------------------
# install_commands
# ---------------------------------------------------------------------------
def test_install_commands_creates_dir_and_copies(isolated):
    _, _, commands = isolated
    n, skipped = setup_mod.install_commands()
    assert n >= 5  # statusbar + 4 sub-commands
    assert skipped == []
    assert commands.is_dir()
    md_files = list(commands.glob("statusbar*.md"))
    assert len(md_files) >= 5


def test_install_commands_idempotent_when_unchanged(isolated):
    setup_mod.install_commands()
    n2, skipped2 = setup_mod.install_commands()
    # Identical content → counted as installed (no-op), nothing skipped
    assert n2 >= 5
    assert skipped2 == []


def test_install_commands_skips_modified_user_files(isolated):
    _, _, commands = isolated
    setup_mod.install_commands()
    # User edited one of our commands
    edited = commands / "statusbar.md"
    edited.write_text("# Locally customized\n", encoding="utf-8")

    n, skipped = setup_mod.install_commands()
    assert any("statusbar.md" in s for s in skipped), f"expected skip, got: {skipped}"
    # User edit preserved
    assert edited.read_text(encoding="utf-8") == "# Locally customized\n"


def test_install_commands_force_overwrites_user_edits(isolated):
    _, _, commands = isolated
    setup_mod.install_commands()
    edited = commands / "statusbar.md"
    edited.write_text("# Locally customized\n", encoding="utf-8")

    n, skipped = setup_mod.install_commands(force=True)
    assert skipped == []
    assert "Locally customized" not in edited.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# run_setup return code
# ---------------------------------------------------------------------------
def test_run_setup_returns_zero_on_clean_install(isolated, capsys):
    rc = setup_mod.run_setup(verbose=False)
    assert rc == 0


def test_run_setup_partial_failure_returns_one(isolated, monkeypatch, capsys):
    """If statusLine is foreign (so we don't write it) but commands install
    fine, run_setup returns 1 (partial)."""
    _, settings, _ = isolated
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps({
        "statusLine": {"type": "command", "command": "starship"}
    }) + "\n", encoding="utf-8")
    rc = setup_mod.run_setup(verbose=False)
    assert rc == 1
