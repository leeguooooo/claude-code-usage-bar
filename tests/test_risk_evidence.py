"""Regression checks for risk evidence boundaries, not ban prediction."""
import json
from types import SimpleNamespace

import pytest

from claude_statusbar import doctor, fp_risk, ip_risk
from claude_statusbar import _ip_risk_refresh as refresh


@pytest.mark.parametrize("timezone", ["Asia/Shanghai", "Asia/Urumqi", "America/New_York", None])
def test_timezone_cannot_escalate_a_configuration_notice(monkeypatch, timezone):
    monkeypatch.setattr(fp_risk, "system_timezone", lambda: pytest.fail("must not inspect timezone"))
    monkeypatch.setenv("TZ", timezone or "")
    text, level = fp_risk.fp_risk_line({"ANTHROPIC_BASE_URL": "https://user:SECRET@private.example/v1?token=SECRET"})
    assert level == "warn"
    for value in ["watermark", "Taipei", "SECRET", "private.example", "ban"]:
        assert value not in text


def test_independent_family_hazard_wins_over_geolocation_difference():
    entry = {"risk": 0, "families": {"v4": {"loc": "US"}, "v6": {"loc": "JP", "verdict": "ban-risk", "type": "vpn"}}}
    assert "network risk signal" in ip_risk.line_text(entry)
    assert ip_risk.risk_level(entry) == "crit"
    entry["families"]["v6"]["verdict"] = "safe"
    assert "unverified" in ip_risk.line_text(entry)
    assert ip_risk.risk_level(entry) == "warn"
    entry["risk"] = 90
    assert ip_risk.line_text(entry).startswith("✗ ip risk 90")


def test_repeated_failures_keep_original_evidence_and_mark_it_stale(tmp_path, monkeypatch):
    monkeypatch.setattr(ip_risk, "_cache_root", lambda: tmp_path)
    original = {"ok": True, "risk": 90, "type": "VPN", "ip": "192.0.2.1", "ts": 100, "checked_ts": 100,
                "families": {"v6": {"loc": "HK"}}}
    ip_risk.write_cache_atomic(original)
    monkeypatch.setattr(refresh, "egress_ip", lambda: (_ for _ in ()).throw(OSError("offline")))
    monkeypatch.setattr(refresh.time, "time", lambda: 200)
    refresh._refresh_locked()
    monkeypatch.setattr(refresh.time, "time", lambda: 300)
    refresh._refresh_locked()
    entry = ip_risk.read_cache()
    assert entry["last_good"]["ts"] == 100
    assert entry["last_good"]["families"] == original["families"]
    assert "last_good" not in entry["last_good"]
    text, level = ip_risk.cached_status(entry, now=300)
    assert "refresh failed" in text and "current status unknown" in text
    assert level == "crit"


@pytest.mark.parametrize("risk", [None, "bad", float("nan"), float("inf"), -1, 101, True])
def test_invalid_reading_is_unknown_not_clean(risk):
    entry = {"ok": True, "risk": risk, "ts": 100}
    assert ip_risk.cache_state(entry, now=100) == "unknown"
    assert "unknown" in ip_risk.cached_status(entry, now=100)[0]


@pytest.mark.parametrize("timestamp", [float("nan"), float("inf"), 1000000])
def test_invalid_or_future_clock_cannot_freeze_refresh(timestamp):
    entry = {"ok": True, "risk": 0, "ts": timestamp, "checked_ts": timestamp}
    assert ip_risk.should_refresh(entry, now=100)
    assert not ip_risk.is_fresh(entry, now=100)
    assert "unknown" in ip_risk.cached_status(entry, now=100)[0]


def test_unknown_and_stale_clean_readings_are_visible():
    assert "unknown" in ip_risk.cached_status(None)[0]
    assert "unknown" in ip_risk.cached_status({"ok": False})[0]
    assert ip_risk.cached_status({"ok": True, "risk": 0, "ts": 100}, now=100) == ("", "ok")
    assert "unknown" in ip_risk.cached_status({"ok": True, "risk": 0, "ts": 100}, now=1000)[0]


def test_doctor_risk_details_never_probe_spawn_scan_or_print_sensitive_values(monkeypatch, capsys):
    from claude_statusbar import config
    import subprocess
    import urllib.request
    entry = {"ok": True, "risk": 90, "ts": 1, "ip": "192.0.2.123",
             "families": {"v6": {"ip": "2001:db8::123", "loc": "HK"}}}
    monkeypatch.setattr(ip_risk, "read_cache", lambda: entry)
    monkeypatch.setattr(config, "load_config", lambda: SimpleNamespace(show_ip_risk=True))
    monkeypatch.setattr(ip_risk, "ensure_fresh", lambda *a, **k: pytest.fail("no refresh"))
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("no scanner/subprocess"))
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: pytest.fail("no network"))
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://user:SECRET@private.example/")
    doctor.risk_details()
    text = capsys.readouterr().out
    assert "ip-check.leeguoo.com" in text and "app.leeguoo.com/thermo" in text
    for value in ["SECRET", "private.example", "192.0.2.123", "2001:db8::123"]:
        assert value not in text
    assert "partial" in text


def test_retained_cache_contains_only_whitelisted_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(ip_risk, "_cache_root", lambda: tmp_path)
    ip_risk.write_cache_atomic({"ok": True, "risk": 90, "ts": 1, "token": "PRIVATE"})
    monkeypatch.setattr(refresh, "egress_ip", lambda: (_ for _ in ()).throw(OSError()))
    refresh._refresh_locked()
    assert "PRIVATE" not in json.dumps(ip_risk.read_cache())


@pytest.mark.parametrize("kind", ["http", "https", "all"])
def test_family_probes_do_not_bypass_configured_proxy(monkeypatch, kind):
    monkeypatch.setattr(refresh.urllib.request, "getproxies", lambda: {kind: "socks5://localhost:9999"})
    monkeypatch.setattr(refresh, "_trace_over", lambda *a: pytest.fail("must not probe directly"))
    assert refresh.family_traces() == {}


def test_primary_region_warning_survives_missing_family_coverage():
    entry = {"ok": True, "risk": 0, "country": "HK", "families": {}, "ts": 100}
    text, level = ip_risk.cached_status(entry, now=100)
    assert "HK" in text and "unsupported region" in text
    assert level == "crit"
    assert "WILL" not in text
