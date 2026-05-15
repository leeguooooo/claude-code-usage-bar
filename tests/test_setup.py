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
    skills = tmp_path / ".claude" / "skills"
    monkeypatch.setattr(setup_mod, "SETTINGS_PATH", settings)
    monkeypatch.setattr(setup_mod, "COMMANDS_DIR", commands)
    monkeypatch.setattr(setup_mod, "SKILLS_DIR", skills)
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
    # Since 3.6.0 a fresh install defaults to daemon mode (`<cs> render`),
    # so the command is split into the binary path + " render".
    cmd_path = data["statusLine"]["command"].split()[0]
    assert Path(cmd_path).name in setup_mod.OUR_COMMAND_NAMES
    assert data["statusLine"]["command"].endswith(" render")


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
# install_skills
# ---------------------------------------------------------------------------
def test_install_skills_creates_dir_and_copies(isolated, tmp_path):
    n, skipped = setup_mod.install_skills()
    assert n >= 1
    assert skipped == []
    skills_dir = setup_mod.SKILLS_DIR
    assert skills_dir.is_dir()
    skill_md = skills_dir / "claude-statusbar" / "SKILL.md"
    assert skill_md.is_file(), f"expected SKILL.md at {skill_md}"
    body = skill_md.read_text(encoding="utf-8")
    assert "name: claude-statusbar" in body
    assert "cs config set theme" in body  # smoke-check decision-tree content


def test_install_skills_idempotent_when_unchanged(isolated):
    setup_mod.install_skills()
    n2, skipped2 = setup_mod.install_skills()
    assert n2 >= 1
    assert skipped2 == []


def test_install_skills_skips_modified_user_files(isolated):
    setup_mod.install_skills()
    edited = setup_mod.SKILLS_DIR / "claude-statusbar" / "SKILL.md"
    edited.write_text("# Locally customized skill\n", encoding="utf-8")
    n, skipped = setup_mod.install_skills()
    assert any("SKILL.md" in s for s in skipped), f"expected skip, got: {skipped}"
    assert edited.read_text(encoding="utf-8") == "# Locally customized skill\n"


def test_install_skills_force_overwrites_user_edits(isolated):
    setup_mod.install_skills()
    edited = setup_mod.SKILLS_DIR / "claude-statusbar" / "SKILL.md"
    edited.write_text("# Locally customized skill\n", encoding="utf-8")
    n, skipped = setup_mod.install_skills(force=True)
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


# ---------------------------------------------------------------------------
# ensure_project_statusline_configured
# ---------------------------------------------------------------------------
def test_project_setup_creates_fresh_settings(tmp_path: Path):
    ok, msg = setup_mod.ensure_project_statusline_configured(tmp_path)
    assert ok is True
    assert "Wrote project statusLine" in msg
    data = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert data["statusLine"]["type"] == "command"
    cmd_path = data["statusLine"]["command"].split()[0]
    assert Path(cmd_path).name in setup_mod.OUR_COMMAND_NAMES


def test_project_setup_preserves_existing_keys(tmp_path: Path):
    """Other settings (hooks, permissions, etc.) in the project file must
    survive — we only own statusLine."""
    proj_settings = tmp_path / ".claude" / "settings.json"
    proj_settings.parent.mkdir(parents=True)
    proj_settings.write_text(json.dumps({
        "hooks": {"PostToolUse": [{"matcher": "Edit"}]},
        "permissions": {"deny": ["Bash(rm:*)"]},
    }) + "\n", encoding="utf-8")

    ok, _ = setup_mod.ensure_project_statusline_configured(tmp_path)
    assert ok is True
    data = json.loads(proj_settings.read_text(encoding="utf-8"))
    assert data["hooks"] == {"PostToolUse": [{"matcher": "Edit"}]}
    assert data["permissions"] == {"deny": ["Bash(rm:*)"]}
    assert "statusLine" in data


def test_project_setup_idempotent(tmp_path: Path):
    setup_mod.ensure_project_statusline_configured(tmp_path)
    ok, msg = setup_mod.ensure_project_statusline_configured(tmp_path)
    assert ok is False
    assert "already configured" in msg


def test_project_setup_refuses_to_trample_foreign_statusline(tmp_path: Path):
    proj_settings = tmp_path / ".claude" / "settings.json"
    proj_settings.parent.mkdir(parents=True)
    proj_settings.write_text(json.dumps({
        "statusLine": {"type": "command", "command": "starship-prompt"}
    }) + "\n", encoding="utf-8")

    ok, msg = setup_mod.ensure_project_statusline_configured(tmp_path)
    assert ok is False
    assert "starship-prompt" in msg
    # File must be untouched.
    data = json.loads(proj_settings.read_text(encoding="utf-8"))
    assert data["statusLine"]["command"] == "starship-prompt"


def test_project_setup_missing_directory(tmp_path: Path):
    nope = tmp_path / "does-not-exist"
    ok, msg = setup_mod.ensure_project_statusline_configured(nope)
    assert ok is False
    assert "not found" in msg


def test_project_setup_inline_mode_omits_render_arg(tmp_path: Path):
    """`--inline` (fast=False) must NOT write `cs render` — that would force
    the daemon path on a user who explicitly opted out."""
    ok, _ = setup_mod.ensure_project_statusline_configured(tmp_path, fast=False)
    assert ok is True
    data = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    parts = data["statusLine"]["command"].split()
    assert len(parts) == 1, f"inline mode should be bare binary, got {parts!r}"


def test_project_setup_refuses_unreadable_existing_file(tmp_path: Path):
    """If the existing settings.json can't be read (e.g. permission denied),
    we must NOT silently overwrite it — otherwise a misconfigured project
    loses its settings."""
    import os

    proj_settings = tmp_path / ".claude" / "settings.json"
    proj_settings.parent.mkdir(parents=True)
    proj_settings.write_text(json.dumps({
        "statusLine": {"type": "command", "command": "cs"}
    }) + "\n", encoding="utf-8")
    original = proj_settings.read_bytes()
    proj_settings.chmod(0o000)
    try:
        ok, msg = setup_mod.ensure_project_statusline_configured(tmp_path)
    finally:
        proj_settings.chmod(0o644)

    assert ok is False
    assert "Could not read" in msg
    # Critically: file must be byte-for-byte unchanged.
    assert proj_settings.read_bytes() == original


def test_project_setup_dot_claude_is_a_file(tmp_path: Path):
    """`.claude` existing as a regular file (not a directory) must produce
    a clean error message instead of an uncaught NotADirectoryError."""
    (tmp_path / ".claude").write_text("not a directory", encoding="utf-8")
    ok, msg = setup_mod.ensure_project_statusline_configured(tmp_path)
    assert ok is False
    assert "Could not create" in msg


def test_project_setup_corrupt_existing_json_is_overwritten(tmp_path: Path):
    """Defensive: if the existing settings.json is malformed, we treat it as
    empty and write our statusLine on top (versus crashing or refusing)."""
    proj_settings = tmp_path / ".claude" / "settings.json"
    proj_settings.parent.mkdir(parents=True)
    proj_settings.write_text("{ broken json", encoding="utf-8")
    ok, _ = setup_mod.ensure_project_statusline_configured(tmp_path)
    assert ok is True
    data = json.loads(proj_settings.read_text(encoding="utf-8"))
    assert "statusLine" in data
