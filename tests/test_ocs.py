"""ocs address segment: whoami parsing, cache/TTL, never-block contract, render."""
import json
import os
import stat
import sys
import time

import pytest

from claude_statusbar import ocs
from claude_statusbar.config import StatusbarConfig, set_value
from claude_statusbar.styles import render_identity_line, _strip
from claude_statusbar.identity import IdentityInfo
from claude_statusbar.themes import get_theme

SID = "7d5a5d07-0a91-42bf-8fbf-619f67cf1422"
_REAL_FIND_OCS = ocs.find_ocs  # conftest stubs it per test


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    monkeypatch.setattr(ocs, "find_ocs", _REAL_FIND_OCS)
    return tmp_path


def _fake_ocs(home, payload, code=0):
    """Install a fake `ocs` on PATH that prints payload and exits code."""
    bindir = home / "bin"
    bindir.mkdir(exist_ok=True)
    p = bindir / "ocs"
    p.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        f"assert sys.argv[1:4] == ['whoami', '--json', '--session'], sys.argv\n"
        f"sys.stdout.write({payload!r})\n"
        f"sys.exit({code})\n")
    p.chmod(p.stat().st_mode | stat.S_IXUSR)
    return p


@pytest.mark.parametrize("payload,expected", [
    ({"id": "claude-7d5a5d07", "name": "boss", "session": "x"},
     {"id": "claude-7d5a5d07", "name": "boss"}),
    ({"id": "claude-7d5a5d07", "name": None, "session": "x"},
     {"id": "claude-7d5a5d07", "name": None}),
    # null id → falls back to the session address
    ({"id": None, "name": None, "session": "claude-statusbar-monitor-9f"},
     {"id": "claude-statusbar-monitor-9f", "name": None}),
    # a name equal to the id adds nothing
    ({"id": "claude-7d5a5d07", "name": "claude-7d5a5d07"},
     {"id": "claude-7d5a5d07", "name": None}),
])
def test_parse_whoami(payload, expected):
    assert ocs.parse_whoami(json.dumps(payload)) == expected


@pytest.mark.parametrize("stdout", [
    "", "not json", "[]", json.dumps({"id": None, "session": None}),
    # terminal escapes must never reach the status line
    json.dumps({"id": "claude-\x1b[31mx", "session": None}),
])
def test_parse_whoami_rejects(stdout):
    assert ocs.parse_whoami(stdout) is None


def test_format_label():
    assert ocs.format_label({"ok": True, "id": "claude-1", "name": "boss"}) == "boss · claude-1"
    assert ocs.format_label({"ok": True, "id": "claude-1", "name": None}) == "claude-1"
    assert ocs.format_label({"ok": False}) == ""
    assert ocs.format_label(None) == ""


def test_find_ocs_falls_back_to_local_bin(home, monkeypatch):
    assert ocs.find_ocs() is None
    local = home / ".local" / "bin"
    local.mkdir(parents=True)
    p = local / "ocs"
    p.write_text("#!/bin/sh\n")
    p.chmod(0o755)
    assert ocs.find_ocs() == str(p)


def test_hidden_without_ocs_and_no_spawn(home, monkeypatch):
    calls = []
    monkeypatch.setattr(ocs, "mark_inflight", lambda sid: calls.append(sid))
    assert ocs.ocs_label(SID) == ""
    assert calls == []


def test_refresh_writes_cache_and_label(home):
    _fake_ocs(home, json.dumps({"id": "claude-7d5a5d07", "name": "boss"}))
    ocs.refresh(SID)
    entry = ocs.read_cache(SID)
    assert entry["ok"] is True
    assert ocs.ocs_label(SID, spawn=False) == "boss · claude-7d5a5d07"


def test_old_ocs_exit_1_hides(home):
    _fake_ocs(home, "ocs: unknown flag: --json", code=1)
    ocs.refresh(SID)
    assert ocs.read_cache(SID)["ok"] is False
    assert ocs.ocs_label(SID, spawn=False) == ""


def test_stale_cache_serves_last_label_and_spawns(home, monkeypatch):
    _fake_ocs(home, "{}")
    ocs.write_cache_atomic(SID, {"ts": time.time() - 999, "ok": True,
                                 "id": "claude-7d5a5d07", "name": "old"})
    spawned = []
    import subprocess
    monkeypatch.setattr(subprocess, "Popen",
                        lambda argv, **kw: spawned.append(argv))
    assert ocs.ocs_label(SID) == "old · claude-7d5a5d07"
    assert spawned and spawned[0][1:] == ["-m", "claude_statusbar.ocs", SID]
    # inflight marker suppresses a second spawn on the next render
    ocs.ocs_label(SID)
    assert len(spawned) == 1


def test_daemon_path_uses_refresh_pool(home, monkeypatch):
    _fake_ocs(home, "{}")
    from claude_statusbar import identity, refresh_pool
    monkeypatch.setattr(identity, "_BACKGROUND_COLLECTORS", True)
    submitted = []
    monkeypatch.setattr(refresh_pool, "submit",
                        lambda key, fn, *a: submitted.append(key))
    assert ocs.ocs_label(SID) == ""
    assert submitted == [("ocs", SID)]


@pytest.mark.parametrize("sid", ["", "-rf", "a b", "x" * 200])
def test_bad_session_ids_rejected(home, sid):
    _fake_ocs(home, "{}")
    assert ocs.ocs_label(sid) == ""


def test_show_ocs_config_default_and_set(home):
    assert StatusbarConfig().show_ocs is True
    assert set_value("show_ocs", "false", path=home / "cfg.json").show_ocs is False


def _info():
    return IdentityInfo(project_name="proj", in_git=True, branch="main",
                        detached=False, worktree_name=None, toplevel="/p")


def test_identity_line_renders_ocs():
    theme = get_theme("graphite")
    line = render_identity_line(_info(), theme=theme, dirty=False,
                                ocs_text="boss · claude-7d5a5d07")
    assert "ocs boss · claude-7d5a5d07" in _strip(line)
    plain = render_identity_line(_info(), theme=theme, dirty=False,
                                 ocs_text="claude-7d5a5d07", use_color=False)
    assert plain.endswith(" · ocs claude-7d5a5d07")
