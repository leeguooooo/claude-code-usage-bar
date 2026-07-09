import json

from claude_statusbar.config import StatusbarConfig, _BOOL_KEYS, set_value
from claude_statusbar.party import read_party_status, workspace_id
from claude_statusbar.styles import render, render_party_line
from claude_statusbar.themes import get_theme


def test_workspace_id_matches_agentparty_fixtures():
    assert workspace_id("/Users/leo/github.com/agentparty") == (
        "agentparty-db745cf4d141394a"
    )
    assert workspace_id("/tmp/Agent Party Demo") == (
        "agent-party-demo-fe44d3b43c263f52"
    )
    assert workspace_id("/work/--") == "workspace-b4972acd009ce462"


def test_missing_status_is_silent(tmp_path):
    assert read_party_status("/tmp/no-party", home=tmp_path) is None


def test_reads_statusline_cache_and_renders_no_color(tmp_path):
    cwd = tmp_path / "Agent Party Demo"
    cwd.mkdir()
    state_dir = tmp_path / "state" / workspace_id(cwd)
    state_dir.mkdir(parents=True)
    now = 1_800_000_000.0
    (state_dir / "statusline.json").write_text(json.dumps({
        "version": 1,
        "updated_at": int(now * 1000),
        "channel": "#agentparty",
        "server": "local",
        "identity": {"name": "xdream-agent", "kind": "agent", "role": "builder"},
        "unread": 3,
        "last_message": {
            "from": "bob",
            "preview": "shipped the auth patch",
            "ts": int(now - 120),
        },
        "listener": {
            "mode": "serve",
            "pid": 1,
            "heartbeat_at": int(now * 1000),
        },
    }), encoding="utf-8")

    status = read_party_status(cwd, now=now, home=tmp_path)
    assert status is not None
    assert status.channel == "#agentparty"
    assert status.identity_name == "xdream-agent"
    assert status.unread == 3
    line = render_party_line(status, theme=get_theme("graphite"), use_color=False)
    assert "🎈 #agentparty" in line
    assert "🤖 xdream-agent" in line
    assert "👂serve" in line
    assert "3 unread" in line
    assert "bob: shipped the auth patch 2m" in line


def test_stale_status_and_dead_listener_degrade(tmp_path):
    cwd = tmp_path / "repo"
    cwd.mkdir()
    state_dir = tmp_path / "state" / workspace_id(cwd)
    state_dir.mkdir(parents=True)
    now = 1_800_000_000.0
    (state_dir / "statusline.json").write_text(json.dumps({
        "updated_at": int((now - 700) * 1000),
        "channel": "#agentparty",
        "identity": {"name": "leo", "kind": "human"},
        "listener": {
            "mode": "watch",
            "pid": 99999999,
            "heartbeat_at": int((now - 700) * 1000),
        },
    }), encoding="utf-8")

    status = read_party_status(cwd, now=now, home=tmp_path)
    assert status is not None
    assert status.fresh is False
    assert status.listener_alive is False
    assert status.listener_stale is True
    line = render_party_line(status, theme=get_theme("graphite"), use_color=False)
    assert "👤 leo" in line
    assert "👂watch down" in line
    assert "stale" in line


def test_dispatcher_appends_party_line():
    from claude_statusbar.party import PartyStatus

    out = render(
        "classic",
        msgs_pct=10, weekly_pct=20, model="Opus 4.7",
        reset_5h="4h", reset_7d="6d",
        use_color=False, theme=get_theme("graphite"),
        party=PartyStatus(channel="#agentparty", identity_name="agent"),
    )
    assert "\n" in out
    assert "🎈 #agentparty" in out


def test_show_party_config_default_and_set(tmp_path):
    p = tmp_path / "cfg.json"
    assert StatusbarConfig().show_party is True
    assert "show_party" in _BOOL_KEYS
    cfg = set_value("show_party", "off", path=p)
    assert cfg.show_party is False
