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
            "heartbeat_ts": int(now * 1000),
        },
    }), encoding="utf-8")

    status = read_party_status(cwd, now=now, home=tmp_path)
    assert status is not None
    assert status.channel == "#agentparty"
    assert status.identity_name == "xdream-agent"
    assert status.unread == 3
    assert status.listener_stale is False
    line = render_party_line(status, theme=get_theme("graphite"), use_color=False)
    head, msg = line.split("\n")
    assert "#agentparty" in head
    assert "⬡ xdream-agent" in head
    assert "◉ serving" in head
    assert "3 unread" in head
    # Unread and not mentioned → filled dot, no @ badge; message on its own line.
    assert msg == "   ↳ ●  bob  shipped the auth patch 2m"


def test_live_watch_listener_is_not_reported_as_down(tmp_path):
    """Regression: the contract field is `heartbeat_ts`, not `heartbeat_at`.

    Reading only `heartbeat_at` made every live listener render as "down".
    """
    import os

    cwd = tmp_path / "repo"
    cwd.mkdir()
    state_dir = tmp_path / "state" / workspace_id(cwd)
    state_dir.mkdir(parents=True)
    now = 1_800_000_000.0
    (state_dir / "statusline.json").write_text(json.dumps({
        "updated_at": int(now * 1000),
        "channel": "seamail",
        "identity": {"name": "leo-zego-voice", "kind": "agent"},
        "listener": {"mode": "watch", "pid": os.getpid(),
                     "heartbeat_ts": int(now * 1000)},
    }), encoding="utf-8")

    status = read_party_status(cwd, now=now, home=tmp_path)
    assert status.listener_alive is True
    assert status.listener_stale is False
    line = render_party_line(status, theme=get_theme("graphite"), use_color=False)
    assert "◉ watching" in line
    assert "down" not in line


def test_mention_of_self_is_badged(tmp_path):
    cwd = tmp_path / "repo"
    cwd.mkdir()
    state_dir = tmp_path / "state" / workspace_id(cwd)
    state_dir.mkdir(parents=True)
    now = 1_800_000_000.0
    (state_dir / "statusline.json").write_text(json.dumps({
        "updated_at": int(now * 1000),
        "channel": "seamail",
        "identity": {"name": "leo-zego-im", "kind": "agent"},
        "unread": 0,
        "last_message": {"from": "Jarvis", "ts": int(now - 60),
                         "preview": "@karl-ag @leo-zego-im ping"},
    }), encoding="utf-8")

    status = read_party_status(cwd, now=now, home=tmp_path)
    assert status.mentioned is True
    msg = render_party_line(status, theme=get_theme("graphite"),
                            use_color=False).split("\n")[1]
    # Read (unread == 0) but mentioned → hollow dot + @ badge.
    assert msg == "   ↳ ○@ Jarvis  @karl-ag @leo-zego-im ping 1m"


def test_mention_requires_exact_identity(tmp_path):
    """`@leo-zego-im` must not count as a mention of `leo-zego`."""
    from claude_statusbar.party import _is_mentioned

    assert _is_mentioned("@leo-zego-im ping", "leo-zego") is False
    assert _is_mentioned("@leo-zego-im ping", "leo-zego-im") is True
    assert _is_mentioned("hi @bob, look", "bob") is True
    assert _is_mentioned("email bob@x.com", "x") is False


def test_no_listener_key_reads_as_not_listening(tmp_path):
    cwd = tmp_path / "repo"
    cwd.mkdir()
    state_dir = tmp_path / "state" / workspace_id(cwd)
    state_dir.mkdir(parents=True)
    now = 1_800_000_000.0
    (state_dir / "statusline.json").write_text(json.dumps({
        "updated_at": int(now * 1000),
        "channel": "seamail",
        "identity": {"name": "leo", "kind": "agent"},
    }), encoding="utf-8")

    status = read_party_status(cwd, now=now, home=tmp_path)
    assert status.listener_present is False
    line = render_party_line(status, theme=get_theme("graphite"), use_color=False)
    assert "◌ not listening" in line


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
            "heartbeat_ts": int((now - 700) * 1000),
        },
    }), encoding="utf-8")

    status = read_party_status(cwd, now=now, home=tmp_path)
    assert status is not None
    assert status.fresh is False
    assert status.listener_alive is False
    assert status.listener_stale is True
    line = render_party_line(status, theme=get_theme("graphite"), use_color=False)
    assert "⬢ leo" in line
    assert "⊘ listener down" in line
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
    assert "#agentparty" in out


def test_show_party_config_default_and_set(tmp_path):
    p = tmp_path / "cfg.json"
    assert StatusbarConfig().show_party is True
    assert "show_party" in _BOOL_KEYS
    cfg = set_value("show_party", "off", path=p)
    assert cfg.show_party is False


def test_mentions_only_probe_is_memoised_per_pid(monkeypatch):
    """The `ps` fork costs ~4ms — about half a warm render. A pid's argv never
    changes, so probe it once."""
    from claude_statusbar import party

    party._MENTIONS_ONLY_CACHE.clear()
    calls = []

    class _Proc:
        stdout = "party watch seamail --mentions-only"

    def _fake_run(*a, **k):
        calls.append(a)
        return _Proc()

    import subprocess
    monkeypatch.setattr(subprocess, "run", _fake_run)

    assert party._listener_mentions_only(4242) is True
    assert party._listener_mentions_only(4242) is True
    assert party._listener_mentions_only(4242) is True
    assert len(calls) == 1, f"forked ps {len(calls)}x for one pid"

    # A different pid must be probed on its own.
    assert party._listener_mentions_only(4243) is True
    assert len(calls) == 2
    party._MENTIONS_ONLY_CACHE.clear()


def test_mentions_only_probe_failure_is_not_cached(monkeypatch):
    """A transient ps failure must not pin `False` for the pid's lifetime."""
    from claude_statusbar import party

    party._MENTIONS_ONLY_CACHE.clear()
    import subprocess

    def _boom(*a, **k):
        raise OSError("no fork for you")
    monkeypatch.setattr(subprocess, "run", _boom)
    assert party._listener_mentions_only(555) is False
    assert 555 not in party._MENTIONS_ONLY_CACHE

    class _Proc:
        stdout = "party watch c --mentions-only"
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc())
    assert party._listener_mentions_only(555) is True
    party._MENTIONS_ONLY_CACHE.clear()
