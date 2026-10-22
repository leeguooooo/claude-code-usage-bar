# Custom-endpoint notices describe configuration, not payloads or account state.
import pytest

import claude_statusbar.fp_risk as fp_risk


def test_no_relay_is_silent(monkeypatch):
    monkeypatch.setattr(fp_risk, "system_timezone", lambda: "Asia/Shanghai")
    text, level = fp_risk.fp_risk_line({"ANTHROPIC_BASE_URL": ""})
    assert text == ""
    # Official settings do not trigger a custom-endpoint notice.
    text, _ = fp_risk.fp_risk_line(
        {"ANTHROPIC_BASE_URL": "https://api.anthropic.com"})
    assert text == ""


@pytest.mark.parametrize("base_url", [
    "HTTP://LOCALHOST:8787",
    "http://127.0.0.1:8787",
    "http://127.42.0.9:8787",
    "http://[::1]:8787",
])
def test_loopback_base_url_is_silent(monkeypatch, base_url):
    monkeypatch.setattr(fp_risk, "system_timezone", lambda: "Asia/Shanghai")
    assert fp_risk.fp_risk_line(
        {"ANTHROPIC_BASE_URL": base_url}
    ) == ("", "ok")


@pytest.mark.parametrize("base_url", [
    "http://192.0.2.1:8787",
    "http://[2001:db8::1]:8787",
    "http://localhost.example.com:8787",
    "http://127.0.0.1.example.com:8787",
])
def test_remote_and_loopback_lookalikes_still_warn(monkeypatch, base_url):
    monkeypatch.setattr(fp_risk, "system_timezone", lambda: "America/New_York")
    text, level = fp_risk.fp_risk_line({"ANTHROPIC_BASE_URL": base_url})
    assert level == "warn"
    assert "custom API endpoint" in text


def test_relay_plus_cn_timezone_is_configuration_notice(monkeypatch):
    monkeypatch.setattr(fp_risk, "system_timezone", lambda: "Asia/Shanghai")
    text, level = fp_risk.fp_risk_line(
        {"ANTHROPIC_BASE_URL": "https://relay.example.com"})
    assert level == "warn"
    assert "watermark" not in text and "timezone" not in text
    assert len(text.split("\n")) == 2
    # Advice points to explicit inspection, not a timezone change.
    assert "Asia/Taipei" not in text
    assert "cs doctor" in text


def test_relay_urumqi_is_not_critical(monkeypatch):
    monkeypatch.setattr(fp_risk, "system_timezone", lambda: "Asia/Urumqi")
    text, level = fp_risk.fp_risk_line({"ANTHROPIC_BASE_URL": "relay.example.com"})
    assert level == "warn"


def test_relay_non_marked_tz_warns(monkeypatch):
    # A remote custom endpoint gets the same notice in every timezone.
    monkeypatch.setattr(fp_risk, "system_timezone", lambda: "America/New_York")
    text, level = fp_risk.fp_risk_line(
        {"ANTHROPIC_BASE_URL": "https://relay.example.com"})
    assert level == "warn"
    assert "custom API endpoint" in text and "watermark" not in text


def test_unresolved_tz_still_warns_on_relay(monkeypatch):
    # No timezone inference is required for a configuration notice.
    monkeypatch.setattr(fp_risk, "system_timezone", lambda: None)
    text, level = fp_risk.fp_risk_line(
        {"ANTHROPIC_BASE_URL": "https://relay.example.com"})
    assert level == "warn"


def test_lookalike_host_not_treated_as_official(monkeypatch):
    monkeypatch.setattr(fp_risk, "system_timezone", lambda: "Asia/Shanghai")
    text, _ = fp_risk.fp_risk_line(
        {"ANTHROPIC_BASE_URL": "https://notapi.anthropic.com.evil"})
    assert text != ""


def test_timezone_reads_TZ_env(monkeypatch):
    monkeypatch.setenv("TZ", "Asia/Shanghai")
    assert fp_risk.system_timezone() == "Asia/Shanghai"


def test_render_appends_fp_line():
    from claude_statusbar.styles import render
    out = render("classic", msgs_pct=10, weekly_pct=5, reset_5h="1h",
                 reset_7d="2d", model="M", use_color=False,
                 fp_line_text="⚠ relay + CN timezone — requests are "
                              "fingerprintable, account-ban risk",
                 fp_line_level="warn")
    assert out.split("\n")[-1].startswith("⚠ relay + CN timezone")


def test_render_no_fp_line_by_default():
    from claude_statusbar.styles import render
    out = render("classic", msgs_pct=10, weekly_pct=5, reset_5h="1h",
                 reset_7d="2d", model="M", use_color=False)
    assert "fingerprint" not in out
