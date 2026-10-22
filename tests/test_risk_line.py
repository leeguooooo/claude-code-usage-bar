"""One-line, localized rendering of network / endpoint findings."""
import pytest

from claude_statusbar import fp_risk, i18n, ip_risk
from claude_statusbar.risk_line import format_finding
from claude_statusbar.styles import render
from claude_statusbar.themes import get_theme

THEME = get_theme("graphite")
CN_V6 = {"ok": True, "risk": 0,
         "families": {"v4": {"loc": "US"}, "v6": {"loc": "CN"}}}


def plain(f, lang):
    return format_finding(f, theme=THEME, lang=lang, use_color=False)


def test_region_finding_one_line_both_languages():
    f = ip_risk.finding(CN_V6)
    assert plain(f, "en") == "✗ IPv6 CN │ unsupported region │ route unverified · cs doctor"
    assert plain(f, "zh") == "✗ IPv6 CN │ 不支持的地区 │ 实际路线未验证 · cs doctor"
    assert f.legacy == ip_risk.line_text(CN_V6)


def test_score_finding_and_last_known_note():
    entry = {"ok": True, "risk": 85, "type": "hosting", "ts": 100, "checked_ts": 100}
    f = ip_risk.finding(entry)
    assert plain(f, "zh") == "✗ ip 85/100 hosting │ 网络有风险 │ 登录前先检查网络 · cs doctor"
    failed = {"ok": False, "ts": 200, "checked_ts": 200, "last_good": entry}
    f2, level = ip_risk.cached_finding(failed, now=200)
    assert level == "crit"
    assert plain(f2, "en") == ("✗ ip 85/100 hosting │ risky network (last known; refresh failed)"
                               " │ current status unknown · cs doctor")
    assert f2.legacy == ip_risk.cached_status(failed, now=200)[0]
    assert "网络有风险（上次结果；刷新失败）" in plain(f2, "zh")


def test_unknown_and_endpoint_notice():
    f, level = ip_risk.cached_finding(None)
    assert plain(f, "zh") == "⚠ ip ? │ 检测不可用 │ 状态未知 · cs doctor"
    g = fp_risk.fp_risk_finding({"ANTHROPIC_BASE_URL": "https://relay.example.com"})
    assert plain(g, "zh") == "◌ api 自定义端点 │ 请求元数据未检查 │ 检查遥测设置 · cs doctor"
    assert g.legacy == fp_risk.fp_risk_line({"ANTHROPIC_BASE_URL": "https://relay.example.com"})[0]


def test_render_uses_single_line_when_finding_given():
    f = ip_risk.finding(CN_V6)
    out = render("aurora", msgs_pct=1, weekly_pct=1, reset_5h="1h", reset_7d="1d",
                 model="Opus", use_color=False, ip_line_text=f.legacy,
                 ip_line_level="crit", ip_finding=f, risk_lang="zh")
    lines = out.split("\n")
    assert lines[-1] == "✗ IPv6 CN │ 不支持的地区 │ 实际路线未验证 · cs doctor"
    assert "↳" not in out


@pytest.mark.parametrize("tag,expected", [("zh-Hans-JP", "zh"), ("zh_CN.UTF-8", "zh"),
                                          ("en_US.UTF-8", "en"), ("ja_JP", "en"),
                                          ("C", None), ("", None)])
def test_normalize(tag, expected):
    assert i18n._normalize(tag) == expected


def test_macos_prefers_apple_languages_over_lang(monkeypatch):
    monkeypatch.setattr(i18n.sys, "platform", "darwin")
    monkeypatch.setattr(i18n, "_macos_lang", lambda: "zh")
    assert i18n.system_lang({"LANG": "en_US.UTF-8"}) == "zh"
    monkeypatch.setattr(i18n, "_macos_lang", lambda: None)
    assert i18n.system_lang({"LANG": "zh_CN.UTF-8"}) == "zh"
    assert i18n.system_lang({}) == "en"


def test_explicit_setting_wins():
    assert i18n.ui_lang("en") == "en" and i18n.ui_lang("zh") == "zh"
