# Egress-IP risk segment (show_ip_risk): render path reads cache only; a
# detached _ip_risk_refresh prober (proxycheck.io) rewrites it every 30 min.
import json
import time

import claude_statusbar.ip_risk as ip_risk
import claude_statusbar._ip_risk_refresh as refresh


def _iso(tmp_path, monkeypatch):
    monkeypatch.setattr(ip_risk, "_cache_root", lambda: tmp_path)


# --- levels & text ---

def test_levels_follow_proxycheck_bands():
    assert ip_risk.risk_level({"risk": 0, "proxy": "no"}) == "ok"
    assert ip_risk.risk_level({"risk": 33, "proxy": "no"}) == "ok"
    assert ip_risk.risk_level({"risk": 34, "proxy": "no"}) == "warn"
    assert ip_risk.risk_level({"risk": 67, "proxy": "no"}) == "crit"
    # proxy verdict is at least warn even with a low score
    assert ip_risk.risk_level({"risk": 5, "proxy": "yes"}) == "warn"


def test_segment_text_formats():
    assert ip_risk.segment_text({"risk": 0, "proxy": "no"}) == "ip✓"
    assert ip_risk.segment_text({"risk": 45, "proxy": "no"}) == "ip⚠45"
    assert ip_risk.segment_text({"risk": 82, "proxy": "no"}) == "ip✗82"


# --- cache / freshness / spawn ---

def test_fresh_ok_cache_renders_without_spawn(tmp_path, monkeypatch):
    _iso(tmp_path, monkeypatch)
    ip_risk.write_cache_atomic({"ok": True, "risk": 12, "proxy": "no",
                                "ts": time.time()})
    spawned = []
    monkeypatch.setattr(ip_risk, "mark_inflight",
                        lambda: spawned.append(1))
    text, level = ip_risk.ip_risk_segment()
    assert (text, level) == ("ip✓", "ok")
    assert not spawned


def test_stale_cache_keeps_last_reading_and_spawns(tmp_path, monkeypatch):
    _iso(tmp_path, monkeypatch)
    ip_risk.write_cache_atomic({"ok": True, "risk": 70, "proxy": "yes",
                                "ts": time.time() - ip_risk.IP_RISK_TTL_S - 5})
    spawned = []
    monkeypatch.setattr(ip_risk, "mark_inflight", lambda: spawned.append(1))

    class _P:
        def __init__(self, *a, **k): spawned.append("popen")
    import subprocess
    monkeypatch.setattr(subprocess, "Popen", _P)
    text, level = ip_risk.ip_risk_segment()
    assert (text, level) == ("ip✗70", "crit")
    assert spawned


def test_failed_cache_hides_segment(tmp_path, monkeypatch):
    _iso(tmp_path, monkeypatch)
    ip_risk.write_cache_atomic({"ok": False, "ts": time.time()})
    text, level = ip_risk.ip_risk_segment(spawn=False)
    assert text == ""


def test_failed_entry_retries_sooner_than_ok(tmp_path, monkeypatch):
    _iso(tmp_path, monkeypatch)
    now = time.time()
    assert ip_risk.is_fresh({"ok": False, "ts": now - ip_risk.FAIL_RETRY_S - 1},
                            now=now) is False
    assert ip_risk.is_fresh({"ok": True, "ts": now - ip_risk.FAIL_RETRY_S - 1},
                            now=now) is True


def test_inflight_marker_blocks_double_spawn(tmp_path, monkeypatch):
    _iso(tmp_path, monkeypatch)
    ip_risk.mark_inflight()
    spawned = []

    class _P:
        def __init__(self, *a, **k): spawned.append("popen")
    import subprocess
    monkeypatch.setattr(subprocess, "Popen", _P)
    ip_risk.ip_risk_segment()
    assert not spawned


# --- refresh prober ---

def test_refresh_writes_ok_entry(tmp_path, monkeypatch):
    _iso(tmp_path, monkeypatch)
    responses = {
        "https://api.ipify.org": "9.9.9.9",
        "https://proxycheck.io/v2/9.9.9.9?risk=1&vpn=1": json.dumps(
            {"status": "ok", "9.9.9.9": {"proxy": "yes", "type": "VPN",
                                         "risk": 66}}),
    }
    monkeypatch.setattr(refresh, "_get", lambda url: responses[url])
    refresh.main()
    entry = ip_risk.read_cache()
    assert entry["ok"] is True
    assert entry["risk"] == 66 and entry["proxy"] == "yes"
    assert ip_risk.is_inflight() is False


def test_refresh_failure_preserves_last_good(tmp_path, monkeypatch):
    _iso(tmp_path, monkeypatch)
    ip_risk.write_cache_atomic({"ok": True, "ip": "9.9.9.9", "risk": 3,
                                "proxy": "no", "ts": time.time() - 9999})

    def _boom(url):
        raise OSError("net down")
    monkeypatch.setattr(refresh, "_get", _boom)
    refresh.main()
    entry = ip_risk.read_cache()
    assert entry["ok"] is False
    assert entry["last_good"]["risk"] == 3


# --- identity-line rendering ---

def test_identity_line_renders_ip_chip():
    from claude_statusbar.styles import render_identity_line, get_theme
    from claude_statusbar.identity import IdentityInfo
    info = IdentityInfo(project_name="proj", in_git=False, branch=None,
                        detached=False, worktree_name=None, toplevel=None)
    line = render_identity_line(info, theme=get_theme("graphite"), dirty=None,
                                ip_text="ip⚠45", ip_level="warn",
                                use_color=False)
    assert "· ip⚠45" in line
    colored = render_identity_line(info, theme=get_theme("graphite"),
                                   dirty=None, ip_text="ip✗82",
                                   ip_level="crit", use_color=True)
    assert "ip✗82" in colored
