"""Windows shell-path handling in the statusLine config (issue #42).

Claude Code executes the statusLine command string through a POSIX shell
(Git Bash on Windows), where `\\` is an escape character:
`C:\\Users\\me\\cs.EXE` execs as `C:Usersmecs.EXE` and dies with exit 127
even though the file exists. The old daily self-heal then reverted any
hand-fix, because it defined drift as "string differs from what I'd write
today" and what it would write was the poisoned backslash path.

These tests pin three behaviors:

  1. paths are written with forward slashes, double-quoted when they contain
     spaces (double quotes because cmd.exe has no single-quote semantics);
  2. the daily self-heal repairs only *broken* entries — a working hand-fix
     and user-added CLI flags are never churned;
  3. a poisoned backslash entry is healed in place, argument tail intact.

Backslash basename extraction goes through PureWindowsPath, so every case
here also runs on POSIX CI.
"""

import json

import pytest

from claude_statusbar import setup as setup_mod


def _bs(path) -> str:
    """Backslash form of a real path — what shutil.which returns on Windows."""
    return str(path).replace("/", "\\")


@pytest.fixture
def settings(monkeypatch, tmp_path):
    p = tmp_path / ".claude" / "settings.json"
    p.parent.mkdir(parents=True)
    monkeypatch.setattr(setup_mod, "SETTINGS_PATH", p)
    return p


@pytest.fixture
def cs_exe(tmp_path):
    """A real file standing in for the installed cs.EXE."""
    d = tmp_path / "Scripts"
    d.mkdir()
    exe = d / "cs.EXE"
    exe.write_bytes(b"")
    return exe


# ---------------------------------------------------------------------------
# _shell_path
# ---------------------------------------------------------------------------
def test_shell_path_posixizes_backslashes():
    assert setup_mod._shell_path(r"C:\Users\me\Scripts\cs.EXE") == "C:/Users/me/Scripts/cs.EXE"


def test_shell_path_double_quotes_spaces():
    assert setup_mod._shell_path(r"C:\Users\First Last\Scripts\cs.EXE") == \
        '"C:/Users/First Last/Scripts/cs.EXE"'


def test_shell_path_leaves_posix_untouched():
    assert setup_mod._shell_path("/usr/local/bin/cs") == "/usr/local/bin/cs"
    assert setup_mod._shell_path("cs") == "cs"


# ---------------------------------------------------------------------------
# tokenization — must not eat backslashes the way shlex posix mode does
# ---------------------------------------------------------------------------
def test_command_tokens_preserve_backslashes():
    assert setup_mod._command_tokens(r"C:\Users\me\cs.EXE render") == \
        [r"C:\Users\me\cs.EXE", "render"]


def test_command_tokens_strip_quotes():
    assert setup_mod._command_tokens('"C:/Users/First Last/cs.EXE" render') == \
        ["C:/Users/First Last/cs.EXE", "render"]


def test_split_command_keeps_tail_verbatim():
    tok0, tail = setup_mod._split_command(r"C:\x\cs.EXE --no-auto-update render")
    assert tok0 == r"C:\x\cs.EXE"
    assert tail == " --no-auto-update render"


# ---------------------------------------------------------------------------
# _is_our_statusline — poisoned entries must still read as ours (or the
# heal would treat them as foreign and never fix them)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("cmd,expected", [
    (r"C:\Users\foo\Scripts\cs.EXE", True),
    (r"C:\Users\foo\Scripts\cs.EXE render", True),
    ('"C:/Users/First Last/Scripts/cs.EXE" render', True),
    (r"C:\tools\starship.exe", False),
])
def test_is_our_statusline_backslash_and_quoted(cmd, expected):
    assert setup_mod._is_our_statusline({"type": "command", "command": cmd}) is expected


# ---------------------------------------------------------------------------
# fresh install writes a shell-safe command
# ---------------------------------------------------------------------------
def test_fresh_write_never_contains_backslashes(settings, monkeypatch):
    monkeypatch.setattr(setup_mod, "_resolve_cs_command",
                        lambda: r"C:\py\Scripts\cs.EXE")
    changed, _ = setup_mod.ensure_statusline_configured()
    assert changed is True
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["statusLine"]["command"] == "C:/py/Scripts/cs.EXE render"


def test_fresh_write_quotes_spaced_path(settings, monkeypatch):
    monkeypatch.setattr(setup_mod, "_resolve_cs_command",
                        lambda: r"C:\Users\First Last\Scripts\cs.EXE")
    setup_mod.ensure_statusline_configured()
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["statusLine"]["command"] == \
        '"C:/Users/First Last/Scripts/cs.EXE" render'
    # and the written entry must still be recognized as ours
    assert setup_mod._is_our_statusline(data["statusLine"]) is True


# ---------------------------------------------------------------------------
# daily self-heal (fast=None): repair broken, never churn working
# ---------------------------------------------------------------------------
def test_hand_fix_survives_daily_pass(settings, cs_exe, monkeypatch):
    """The issue #42 loop: forward-slash hand-fix must not be reverted even
    though the resolver still reports the backslash form."""
    hand_fix = cs_exe.as_posix() + " render"
    settings.write_text(json.dumps({"statusLine": {
        "type": "command", "command": hand_fix, "refreshInterval": 1}}),
        encoding="utf-8")
    monkeypatch.setattr(setup_mod, "_resolve_cs_command", lambda: _bs(cs_exe))
    changed, msg = setup_mod.ensure_statusline_configured()
    assert changed is False, f"daily pass churned a working entry: {msg}"
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["statusLine"]["command"] == hand_fix


def test_backslash_entry_healed_in_place_args_survive(settings, cs_exe, monkeypatch):
    """Poisoned entry → forward slashes, user flags untouched."""
    settings.write_text(json.dumps({"statusLine": {
        "type": "command",
        "command": _bs(cs_exe) + " --no-auto-update",
        "refreshInterval": 5}}), encoding="utf-8")
    monkeypatch.setattr(setup_mod, "_is_windows", lambda: True)
    changed, _ = setup_mod.ensure_statusline_configured()
    assert changed is True
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["statusLine"]["command"] == cs_exe.as_posix() + " --no-auto-update"
    assert data["statusLine"]["refreshInterval"] == 5


def test_bare_name_upgraded_to_absolute_tail_preserved(settings, cs_exe, monkeypatch):
    settings.write_text(json.dumps({"statusLine": {
        "type": "command", "command": "cs render", "refreshInterval": 1}}),
        encoding="utf-8")
    monkeypatch.setattr(setup_mod, "_resolve_cs_command", lambda: _bs(cs_exe))
    changed, _ = setup_mod.ensure_statusline_configured()
    assert changed is True
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["statusLine"]["command"] == cs_exe.as_posix() + " render"


def test_stale_path_replaced_tail_preserved(settings, monkeypatch):
    settings.write_text(json.dumps({"statusLine": {
        "type": "command", "command": "/old/missing/cs render",
        "refreshInterval": 1}}), encoding="utf-8")
    monkeypatch.setattr(setup_mod, "_resolve_cs_command", lambda: "/new/path/cs")
    changed, _ = setup_mod.ensure_statusline_configured()
    assert changed is True
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["statusLine"]["command"] == "/new/path/cs render"


def test_module_form_untouched_by_daily_pass(settings, monkeypatch):
    mod_cmd = "C:/py/python.exe -m claude_statusbar.cli render"
    settings.write_text(json.dumps({"statusLine": {
        "type": "command", "command": mod_cmd, "refreshInterval": 1}}),
        encoding="utf-8")
    changed, _ = setup_mod.ensure_statusline_configured()
    assert changed is False
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["statusLine"]["command"] == mod_cmd


# ---------------------------------------------------------------------------
# explicit setup still force-writes the canonical form
# ---------------------------------------------------------------------------
def test_explicit_setup_still_force_writes(settings, cs_exe, monkeypatch):
    """`cs --setup --fast` is an explicit request — canonical rewrite, custom
    flags may drop. Only the *daily* pass is bound to preserve them."""
    settings.write_text(json.dumps({"statusLine": {
        "type": "command",
        "command": cs_exe.as_posix() + " --no-auto-update",
        "refreshInterval": 1}}), encoding="utf-8")
    monkeypatch.setattr(setup_mod, "_resolve_cs_command", lambda: _bs(cs_exe))
    changed, _ = setup_mod.ensure_statusline_configured(fast=True)
    assert changed is True
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["statusLine"]["command"] == cs_exe.as_posix() + " render"
