# Egress-IP risk warning line (show_ip_risk): render path reads cache only; a
# detached _ip_risk_refresh prober (proxycheck.io) rewrites it every 30 min.
# The line only appears above SHOW_THRESHOLD (40) — a clean IP earns silence.
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


def test_line_hidden_at_or_below_threshold():
    assert ip_risk.line_text({"risk": 0}) == ""
    assert ip_risk.line_text({"risk": 40}) == ""


def test_line_warn_and_crit_wording():
    warn = ip_risk.line_text({"risk": 55, "type": "VPN"})
    assert warn.startswith("⚠ ip risk 55/100 (VPN)")
    assert "account ban" in warn
    crit = ip_risk.line_text({"risk": 82, "type": "VPN"})
    assert crit.startswith("✗ ip risk 82/100 (VPN)")
    assert "account-ban" in crit and "switching network" in crit


# --- cache / freshness / spawn ---

def test_fresh_clean_cache_is_silent_and_no_spawn(tmp_path, monkeypatch):
    _iso(tmp_path, monkeypatch)
    ip_risk.write_cache_atomic({"ok": True, "risk": 12, "proxy": "no",
                                "ts": time.time()})
    spawned = []
    monkeypatch.setattr(ip_risk, "mark_inflight",
                        lambda: spawned.append(1))
    text, level = ip_risk.ip_risk_line()
    assert text == ""
    assert not spawned


def test_stale_cache_keeps_last_reading_and_spawns(tmp_path, monkeypatch):
    _iso(tmp_path, monkeypatch)
    ip_risk.write_cache_atomic({"ok": True, "risk": 70, "proxy": "yes",
                                "type": "VPN",
                                "ts": time.time() - ip_risk.IP_RISK_TTL_S - 5})
    spawned = []
    monkeypatch.setattr(ip_risk, "mark_inflight", lambda: spawned.append(1))

    class _P:
        def __init__(self, *a, **k): spawned.append("popen")
    import subprocess
    monkeypatch.setattr(subprocess, "Popen", _P)
    text, level = ip_risk.ip_risk_line()
    assert text.startswith("✗ ip risk 70/100")
    assert level == "crit"
    assert spawned


def test_failed_cache_hides_line(tmp_path, monkeypatch):
    _iso(tmp_path, monkeypatch)
    ip_risk.write_cache_atomic({"ok": False, "ts": time.time()})
    text, level = ip_risk.ip_risk_line(spawn=False)
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
    ip_risk.ip_risk_line()
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


# --- dedicated line rendering (NOT on the git identity line) ---

def test_render_appends_dedicated_ip_line():
    from claude_statusbar.styles import render
    out = render("classic", msgs_pct=10, weekly_pct=5, reset_5h="1h",
                 reset_7d="2d", model="M", use_color=False,
                 ip_line_text="⚠ ip risk 66/100 (VPN) — current ip may risk account ban",
                 ip_line_level="warn")
    lines = out.split("\n")
    assert lines[-1].startswith("⚠ ip risk 66/100")


def test_render_no_ip_line_when_clean():
    from claude_statusbar.styles import render
    out = render("classic", msgs_pct=10, weekly_pct=5, reset_5h="1h",
                 reset_7d="2d", model="M", use_color=False)
    assert "ip risk" not in out


# --- two-tier freshness: cheap IP recheck vs rate-limited proxycheck ---

def test_should_refresh_on_check_ttl_not_risk_ttl(tmp_path, monkeypatch):
    _iso(tmp_path, monkeypatch)
    now = 1000.0
    # risk reading young (well under IP_RISK_TTL_S) but IP not re-checked for
    # longer than IP_CHECK_TTL_S → must still spawn to catch a VPN toggle
    entry = {"ok": True, "ip": "1.1.1.1", "risk": 0, "ts": now,
             "checked_ts": now}
    assert ip_risk.should_refresh(entry, now=now + ip_risk.IP_CHECK_TTL_S + 1)
    assert not ip_risk.should_refresh(entry, now=now + 10)


def test_prober_shortcircuits_when_ip_unchanged(tmp_path, monkeypatch):
    _iso(tmp_path, monkeypatch)
    import time as _t
    ip_risk.write_cache_atomic({"ok": True, "ip": "1.1.1.1", "risk": 5,
                                "proxy": "no", "type": "ISP",
                                "ts": _t.time(), "checked_ts": _t.time() - 999})
    calls = []
    monkeypatch.setattr(refresh, "egress_ip", lambda: "1.1.1.1")
    monkeypatch.setattr(refresh, "risk_for",
                        lambda ip: calls.append(ip) or {"ok": True})
    refresh.main()
    assert calls == []                              # proxycheck skipped
    entry = ip_risk.read_cache()
    assert entry["risk"] == 5                        # old reading kept
    assert entry["checked_ts"] >= entry["ts"]        # check clock advanced


def test_prober_reprobes_when_ip_changed(tmp_path, monkeypatch):
    _iso(tmp_path, monkeypatch)
    import time as _t
    ip_risk.write_cache_atomic({"ok": True, "ip": "1.1.1.1", "risk": 0,
                                "proxy": "no", "ts": _t.time(),
                                "checked_ts": _t.time()})
    monkeypatch.setattr(refresh, "egress_ip", lambda: "2.2.2.2")  # VPN on
    monkeypatch.setattr(refresh, "risk_for",
                        lambda ip: {"ok": True, "ip": ip, "risk": 88,
                                    "proxy": "yes", "type": "VPN"})
    refresh.main()
    entry = ip_risk.read_cache()
    assert entry["ip"] == "2.2.2.2" and entry["risk"] == 88


def test_fp_risk_default_on_ip_risk_default_off():
    from claude_statusbar.config import StatusbarConfig
    cfg = StatusbarConfig()
    assert cfg.show_fp_risk is True     # local-only, silent unless risk
    assert cfg.show_ip_risk is False    # makes a third-party network call
