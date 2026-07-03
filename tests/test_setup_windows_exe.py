"""Windows launcher-shim recognition (issue #32).

On Windows, shutil.which("cs") resolves to a path ending in "cs.EXE" and
pip/pipx write "cs.exe"/"cs.cmd"/"cs.bat" shims. The old exact-name match
against OUR_COMMAND_NAMES failed on those, so `cs doctor` reported
"(not ours)" and `cs --setup` refused to update a valid entry.

Note: tests run on macOS where Path() is PosixPath, so backslash paths
can't be exercised here — basename extraction from "C:\\...\\cs.EXE" only
works on a real WindowsPath. These tests cover the extension/case
normalization, which is the platform-independent part of the fix.
"""

import pytest

from claude_statusbar import setup as setup_mod


# ---------------------------------------------------------------------------
# _normalize_command_name
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name,expected", [
    ("cs", "cs"),
    ("cs.exe", "cs"),
    ("cs.EXE", "cs"),          # shutil.which on Windows returns uppercase ext
    ("cs.cmd", "cs"),
    ("cs.bat", "cs"),
    ("CS.EXE", "cs"),
    ("cstatus.exe", "cstatus"),
    ("claude-statusbar.exe", "claude-statusbar"),
    ("starship.exe", "starship"),   # still not ours after normalization
    ("cs.py", "cs.py"),             # unknown extensions are left alone
])
def test_normalize_command_name(name, expected):
    assert setup_mod._normalize_command_name(name) == expected


# ---------------------------------------------------------------------------
# _is_our_statusline with Windows-style commands
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("entry,expected", [
    ({"type": "command", "command": "cs.EXE"}, True),
    ({"type": "command", "command": "cs.exe"}, True),
    ({"type": "command", "command": "cs.exe render"}, True),
    ({"type": "command", "command": "cs.cmd"}, True),
    ({"type": "command", "command": "cstatus.exe"}, True),
    ({"type": "command", "command": "claude-statusbar.EXE render"}, True),
    # forward-slash absolute path — Path.name works cross-platform for these
    ({"type": "command", "command": "C:/Users/foo/Scripts/cs.EXE"}, True),
    ({"type": "command", "command": "C:/Users/foo/Scripts/cs.exe render"}, True),
    # foreign tools stay foreign even with a shim extension
    ({"type": "command", "command": "starship.exe"}, False),
    ({"type": "command", "command": "C:/tools/tmux-status.exe"}, False),
])
def test_is_our_statusline_windows_shims(entry, expected):
    assert setup_mod._is_our_statusline(entry) is expected


def test_setup_leaves_foreign_exe_alone(monkeypatch, tmp_path):
    """A genuinely foreign .exe entry must still be preserved by --setup."""
    import json
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps(
        {"statusLine": {"type": "command", "command": "starship.exe prompt"}}
    ), encoding="utf-8")
    monkeypatch.setattr(setup_mod, "SETTINGS_PATH", settings)
    changed, msg = setup_mod.ensure_statusline_configured()
    assert changed is False
    assert "different statusLine" in msg


def test_setup_updates_our_exe_entry(monkeypatch, tmp_path):
    """An existing cs.EXE entry is ours — setup may touch it, never refuses."""
    import json
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps(
        {"statusLine": {"type": "command", "command": "C:/py/Scripts/cs.EXE render",
                        "refreshInterval": 1}}
    ), encoding="utf-8")
    monkeypatch.setattr(setup_mod, "SETTINGS_PATH", settings)
    changed, msg = setup_mod.ensure_statusline_configured()
    # It must NOT bail with the "different statusLine" refusal — the entry
    # is recognized as ours, so it's either left as-is or repointed.
    assert "different statusLine" not in msg
