# Relay fingerprint-risk warning line (show_fp_risk): local-only inference —
# relay base URL + a marked system timezone. Never touches the network or the
# outgoing request; it only surfaces what the user's own env already implies.
import claude_statusbar.fp_risk as fp_risk


def test_no_relay_is_silent(monkeypatch):
    monkeypatch.setattr(fp_risk, "system_timezone", lambda: "Asia/Shanghai")
    text, level = fp_risk.fp_risk_line({"ANTHROPIC_BASE_URL": ""})
    assert text == ""
    # official host, even in a marked tz, is unaffected by the watermark
    text, _ = fp_risk.fp_risk_line(
        {"ANTHROPIC_BASE_URL": "https://api.anthropic.com"})
    assert text == ""


def test_relay_plus_marked_tz_is_crit(monkeypatch):
    monkeypatch.setattr(fp_risk, "system_timezone", lambda: "Asia/Shanghai")
    text, level = fp_risk.fp_risk_line(
        {"ANTHROPIC_BASE_URL": "https://relay.example.com"})
    assert level == "crit"
    assert "watermark" in text and "CN timezone" in text
    assert len(text.split("\n")) == 2


def test_relay_urumqi_also_crit(monkeypatch):
    monkeypatch.setattr(fp_risk, "system_timezone", lambda: "Asia/Urumqi")
    text, level = fp_risk.fp_risk_line({"ANTHROPIC_BASE_URL": "relay.example.com"})
    assert level == "crit"


def test_relay_non_marked_tz_warns(monkeypatch):
    # A relay in ANY timezone is fingerprintable (domain/keyword dimension) →
    # at least a warn, not silent.
    monkeypatch.setattr(fp_risk, "system_timezone", lambda: "America/New_York")
    text, level = fp_risk.fp_risk_line(
        {"ANTHROPIC_BASE_URL": "https://relay.example.com"})
    assert level == "warn"
    assert "relay" in text and "watermark" in text


def test_unresolved_tz_still_warns_on_relay(monkeypatch):
    # tz unknown but still a relay → the non-timezone dimensions apply → warn.
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
