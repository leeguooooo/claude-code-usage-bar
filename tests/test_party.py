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


def test_argv_probe_is_memoised_per_pid(monkeypatch):
    """The `ps` fork costs ~4ms — about half a warm render. A pid's argv never
    changes, so probe it once and derive both mentions-only and is-party."""
    from claude_statusbar import party

    party._ARGV_CACHE.clear()
    calls = []

    class _Proc:
        returncode = 0
        stdout = "party watch seamail --mentions-only"

    def _fake_run(*a, **k):
        calls.append(a)
        return _Proc()

    import subprocess
    monkeypatch.setattr(subprocess, "run", _fake_run)

    assert party._listener_mentions_only(4242) is True
    assert party._listener_mentions_only(4242) is True
    assert party._argv_is_party(party._listener_argv(4242)) is True
    assert len(calls) == 1, f"forked ps {len(calls)}x for one pid"

    # A different pid must be probed on its own.
    assert party._listener_mentions_only(4243) is True
    assert len(calls) == 2
    party._ARGV_CACHE.clear()


def test_argv_probe_failure_is_not_cached(monkeypatch):
    """A transient ps failure must not pin an answer for the pid's lifetime."""
    from claude_statusbar import party

    party._ARGV_CACHE.clear()
    import subprocess

    def _boom(*a, **k):
        raise OSError("no fork for you")
    monkeypatch.setattr(subprocess, "run", _boom)
    assert party._listener_argv(555) is None
    assert 555 not in party._ARGV_CACHE

    class _Proc:
        returncode = 0
        stdout = "party watch c --mentions-only"
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc())
    assert party._listener_mentions_only(555) is True
    party._ARGV_CACHE.clear()


def test_argv_is_party_matcher():
    from claude_statusbar.party import _argv_is_party
    assert _argv_is_party("party watch seamail --mentions-only")
    assert _argv_is_party("/Users/leo/.local/bin/party serve dev")
    assert _argv_is_party("bun /x/party watch c")
    assert not _argv_is_party("python3 third_party_tool.py")
    assert not _argv_is_party("vim party-notes.md")   # no space/slash boundary after
    assert not _argv_is_party("compartymaker --run")


def test_alive_party_process_with_stale_heartbeat_is_still_listening(tmp_path, monkeypatch):
    """CLIs older than 0.2.80 heartbeat only on traffic — a quiet channel left
    heartbeat_ts stale and a healthy connected listener rendered as
    "⊘ listener down" (seen live: a serve alive with a 32-minute-old
    heartbeat). An alive, verifiably-party process is listening, whatever the
    heartbeat age."""
    import os
    from claude_statusbar import party

    party._ARGV_CACHE.clear()
    import subprocess

    class _Proc:
        returncode = 0
        stdout = "party serve zego-p-room --on-mention x"
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc())

    cwd = tmp_path / "repo"
    cwd.mkdir()
    state_dir = tmp_path / "state" / workspace_id(cwd)
    state_dir.mkdir(parents=True)
    now = 1_800_000_000.0
    (state_dir / "statusline.json").write_text(json.dumps({
        "updated_at": int(now * 1000),
        "channel": "zego-p-room",
        "identity": {"name": "super-admin-1", "kind": "agent"},
        "listener": {"mode": "serve", "pid": os.getpid(),
                     "heartbeat_ts": int((now - 32 * 60) * 1000)},  # 32min stale
    }), encoding="utf-8")

    status = read_party_status(cwd, now=now, home=tmp_path)
    assert status.listener_alive is True
    assert status.listener_stale is False
    line = render_party_line(status, theme=get_theme("graphite"), use_color=False)
    assert "◉ serving" in line
    assert "down" not in line
    party._ARGV_CACHE.clear()


def test_recycled_pid_with_stale_heartbeat_is_down(tmp_path, monkeypatch):
    """Alive pid + stale heartbeat + argv is NOT a party process → the pid was
    recycled; the listener is genuinely gone."""
    import os
    from claude_statusbar import party

    party._ARGV_CACHE.clear()
    import subprocess

    class _Proc:
        returncode = 0
        stdout = "/usr/bin/vim notes.md"
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc())

    cwd = tmp_path / "repo"
    cwd.mkdir()
    state_dir = tmp_path / "state" / workspace_id(cwd)
    state_dir.mkdir(parents=True)
    now = 1_800_000_000.0
    (state_dir / "statusline.json").write_text(json.dumps({
        "updated_at": int(now * 1000),
        "channel": "dev",
        "identity": {"name": "x", "kind": "agent"},
        "listener": {"mode": "watch", "pid": os.getpid(),
                     "heartbeat_ts": int((now - 32 * 60) * 1000)},
    }), encoding="utf-8")

    status = read_party_status(cwd, now=now, home=tmp_path)
    assert status.listener_stale is True
    line = render_party_line(status, theme=get_theme("graphite"), use_color=False)
    assert "⊘ listener down" in line
    party._ARGV_CACHE.clear()


def test_mentions_only_prefers_contract_field_over_ps(tmp_path, monkeypatch):
    """agentparty >= 0.2.79 writes `listener.mentions_only` into the cache.
    When present it must be used verbatim and the `ps` argv probe must not
    fork at all — the probe stays only as a fallback for older CLIs."""
    import os
    import subprocess
    from claude_statusbar import party

    def _no_fork(*a, **k):
        raise AssertionError("ps must not be forked when the contract field is present")
    monkeypatch.setattr(subprocess, "run", _no_fork)

    cwd = tmp_path / "repo"
    cwd.mkdir()
    state_dir = tmp_path / "state" / workspace_id(cwd)
    state_dir.mkdir(parents=True)
    now = 1_800_000_000.0
    base = {
        "updated_at": int(now * 1000),
        "channel": "seamail",
        "identity": {"name": "leo", "kind": "agent"},
        "listener": {"mode": "watch", "pid": os.getpid(),
                     "heartbeat_ts": int(now * 1000), "mentions_only": True},
    }
    (state_dir / "statusline.json").write_text(json.dumps(base), encoding="utf-8")
    status = read_party_status(cwd, now=now, home=tmp_path)
    assert status.listener_mentions_only is True

    # Field explicitly absent-of-mentions semantics: contract omits it when
    # listening to everything — but a hypothetical false must also be honoured.
    base["listener"] = {"mode": "watch", "pid": os.getpid(),
                        "heartbeat_ts": int(now * 1000), "mentions_only": False}
    (state_dir / "statusline.json").write_text(json.dumps(base), encoding="utf-8")
    status = read_party_status(cwd, now=now, home=tmp_path)
    assert status.listener_mentions_only is False


def test_session_attachment_gate(tmp_path, monkeypatch):
    """The AgentParty cache is cwd-scoped, but sessions sharing a project dir
    don't all join a channel. A session is attached only when its OWN
    transcript shows a party command; the verdict is sticky and later scans
    read only newly appended bytes."""
    from claude_statusbar import party
    from claude_statusbar import daemon as _d

    monkeypatch.setattr(_d, "_cache_dir", lambda: tmp_path)

    t = tmp_path / "transcript.jsonl"
    t.write_text(json.dumps({"type": "user", "text": "hello world"}) + "\n",
                 encoding="utf-8")
    # Unrelated session: no party commands anywhere.
    assert party.session_is_attached(str(t), "sid-a") is False

    # Talking ABOUT AgentParty must not attach.
    t.write_text(json.dumps({"type": "user",
                             "text": "what is agentparty.leeguoo.com?"}) + "\n",
                 encoding="utf-8")
    assert party.session_is_attached(str(t), "sid-b") is False

    # Running a party command attaches — appended AFTER a first scan, so this
    # also proves the incremental tail-scan sees new bytes.
    assert party.session_is_attached(str(t), "sid-c") is False
    with t.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "tool_use",
                            "command": "party send hi --channel dev"}) + "\n")
    assert party.session_is_attached(str(t), "sid-c") is True
    # Sticky: even if the transcript is later truncated, the session stays
    # attached without rescanning.
    t.write_text("", encoding="utf-8")
    assert party.session_is_attached(str(t), "sid-c") is True


def test_attachment_gate_handles_needle_straddling_scans(tmp_path, monkeypatch):
    """An incomplete tool-use record is picked up once its line completes."""
    from claude_statusbar import party
    from claude_statusbar import daemon as _d

    monkeypatch.setattr(_d, "_cache_dir", lambda: tmp_path)
    t = tmp_path / "t.jsonl"
    t.write_bytes(b'{"type":"tool_use","command":"party wa')
    assert party.session_is_attached(str(t), "sid-x") is False
    with t.open("ab") as f:
        f.write(b'tch seamail"}\n')
    assert party.session_is_attached(str(t), "sid-x") is True


def test_same_workspace_sessions_resolve_their_own_identity(tmp_path, monkeypatch):
    """A cwd-scoped status cache must not collapse distinct session configs."""
    from claude_statusbar import daemon as _d
    from claude_statusbar import party

    monkeypatch.setattr(_d, "_cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    cwd = tmp_path / "repo"
    cwd.mkdir()
    state_dir = tmp_path / "state" / workspace_id(cwd)
    state_dir.mkdir(parents=True)
    (state_dir / "statusline.json").write_text(json.dumps({
        "channel": "agentparty",
        "identity": {"name": "last-writer", "kind": "agent"},
    }), encoding="utf-8")

    identities = []
    for session_id, name in (("sid-a", "agent-a"), ("sid-b", "agent-b")):
        config = tmp_path / f"{name}.json"
        config.write_text(json.dumps({
            "token": "must-not-be-rendered",
            "identity": {"name": name, "kind": "agent", "role": "builder"},
        }), encoding="utf-8")
        transcript = tmp_path / f"{session_id}.jsonl"
        config_ref = (str(config) if session_id == "sid-a"
                      else "${TMPDIR:-/tmp}/agent-b.json")
        decoy = tmp_path / f"decoy-{name}.json"
        decoy.write_text(json.dumps({
            "identity": {"name": f"wrong-{name}", "kind": "agent"},
        }), encoding="utf-8")
        transcript.write_text(json.dumps({
            "type": "assistant",
            "message": {"content": [{
                "type": "tool_use",
                "name": "Bash",
                "input": {"command": (
                    f'AGENTPARTY_CONFIG="{config_ref}" '
                    "party send agentparty hi"
                )},
            }]},
        }) + "\n" + json.dumps({
            "type": "user",
            "text": f'example: AGENTPARTY_CONFIG="{decoy}"',
        }) + "\n", encoding="utf-8")

        context = party.session_party_context(
            str(transcript), session_id, cwd=cwd)
        status = read_party_status(
            cwd, home=tmp_path, config_path=context.config_path)
        identities.append(status.identity_name)

    assert identities == ["agent-a", "agent-b"]


def test_same_workspace_sessions_read_their_own_complete_status_slot(tmp_path):
    """Channel, preview and listener must follow the session config too.

    Regression: only overriding the identity still rendered the last writer's
    channel/message/listener, producing combinations such as a leo-code-space
    agent beside an ai-girls stale-listener warning.
    """
    import hashlib

    cwd = tmp_path / "repo"
    cwd.mkdir()
    state_dir = tmp_path / "state" / workspace_id(cwd)
    slots = state_dir / "slots"
    slots.mkdir(parents=True)
    (state_dir / "statusline.json").write_text(json.dumps({
        "channel": "ai-girls",
        "identity": {"name": "ai-girl-zim", "kind": "agent"},
        "last_message": {"from": "wrong", "preview": "wrong channel"},
        "listener": {"mode": "serve", "pid": 99999999},
    }), encoding="utf-8")

    config = tmp_path / "tk-zego-im.json"
    token = "ap_session-token"
    config.write_text(json.dumps({
        "token": token,
        "identity": {
            "name": "tk-zego-im",
            "kind": "agent",
            "role": "agent",
            "channel_scope": "leo-code-space",
        },
    }), encoding="utf-8")
    token_fingerprint = "sha256:" + hashlib.sha256(
        token.encode("utf-8")).hexdigest()[:12]
    slot_key = json.dumps({
        "channel": "leo-code-space",
        "kind": "explicit",
        "path": str(config),
        "token": token_fingerprint,
    }, separators=(",", ":"))
    slot_fingerprint = hashlib.sha256(
        slot_key.encode("utf-8")).hexdigest()[:16]
    (slots / f"statusline-leo-code-space-{slot_fingerprint}.json").write_text(
        json.dumps({
            "channel": "leo-code-space",
            "server": "https://agentparty.pwtk-dev.work",
            "identity": {"name": "tk-zego-im", "kind": "agent"},
            "unread": 6,
            "last_message": {
                "from": "super-admin-leo-space",
                "preview": "headcount fix verified",
            },
        }), encoding="utf-8")

    status = read_party_status(
        cwd, home=tmp_path, config_path=str(config))

    assert status is not None
    assert status.channel == "leo-code-space"
    assert status.server == "https://agentparty.pwtk-dev.work"
    assert status.identity_name == "tk-zego-im"
    assert status.unread == 6
    assert status.last_from == "super-admin-leo-space"
    assert status.last_preview == "headcount fix verified"
    assert status.listener_present is False


def test_session_recovers_older_config_when_cached_temp_file_disappears(
        tmp_path, monkeypatch):
    """A deleted TMPDIR invite config must not stay pinned forever."""
    from claude_statusbar import daemon as _d
    from claude_statusbar import party

    monkeypatch.setattr(_d, "_cache_dir", lambda: tmp_path / "cache")
    cwd = tmp_path / "repo"
    cwd.mkdir()
    persistent = tmp_path / "persistent.json"
    temporary = tmp_path / "temporary.json"
    for path, name in ((persistent, "persistent-agent"),
                       (temporary, "temporary-agent")):
        path.write_text(json.dumps({
            "identity": {"name": name, "kind": "agent"},
        }), encoding="utf-8")
    transcript = tmp_path / "session.jsonl"
    transcript.write_text("\n".join([
        json.dumps({
            "type": "tool_use",
            "command": (
                f'AGENTPARTY_CONFIG="{persistent}" party send first'
            ),
        }),
        json.dumps({
            "type": "tool_use",
            "command": (
                f'AGENTPARTY_CONFIG="{temporary}" party send latest'
            ),
        }),
    ]) + "\n", encoding="utf-8")

    first = party.session_party_context(
        str(transcript), "sid-temp", cwd=cwd)
    assert first.config_path == str(temporary)

    temporary.unlink()
    recovered = party.session_party_context(
        str(transcript), "sid-temp", cwd=cwd)
    assert recovered.config_path == str(persistent)


def test_session_resolves_config_through_simple_shell_variable(
        tmp_path, monkeypatch):
    """Real sessions commonly use ``CFG=... AGENTPARTY_CONFIG=$CFG``."""
    from claude_statusbar import daemon as _d
    from claude_statusbar import party

    monkeypatch.setattr(_d, "_cache_dir", lambda: tmp_path / "cache")
    cwd = tmp_path / "repo"
    cwd.mkdir()
    config = tmp_path / "persistent.json"
    config.write_text(json.dumps({
        "identity": {"name": "tk-zego-im", "kind": "agent"},
    }), encoding="utf-8")
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(json.dumps({
        "type": "tool_use",
        "command": (
            f'cd "{cwd}" CFG="{config}" '
            'AGENTPARTY_CONFIG="$CFG" party history leo-code-space'
        ),
    }) + "\n", encoding="utf-8")

    context = party.session_party_context(
        str(transcript), "sid-variable", cwd=cwd)

    assert context.config_path == str(config)


def test_missing_transcript_is_not_attached(tmp_path, monkeypatch):
    from claude_statusbar import party
    assert party.session_is_attached("/nope/nothing.jsonl", "sid") is False
    assert party.session_is_attached("", "sid") is False
    assert party.session_is_attached("/tmp/x", "") is False
