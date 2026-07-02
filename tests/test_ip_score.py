# Local IP scoring (ip_score) — the plugin-side port of the ip-check service's
# classify + claude-verdict, so the statusbar scores locally from an ipapi.is
# self-check instead of routing through our Worker.
from claude_statusbar import ip_score


def test_clean_residential_is_safe():
    e = ip_score.evaluate({"is_datacenter": False}, "US")
    assert e["risk"] == 0 and e["type"] == "residential"
    assert e["verdict"] == "safe" and e["score"] == 100


def test_datacenter_is_caution_not_ban():
    e = ip_score.evaluate({"is_datacenter": True}, "US")
    assert e["type"] == "hosting" and e["risk"] == 33
    assert e["verdict"] == "caution"          # API/server use is fine
    assert e["score"] == 60


def test_vpn_outscores_datacenter():
    dc = ip_score.classify({"is_datacenter": True})
    vpn = ip_score.classify({"is_vpn": True})
    assert vpn["risk"] > dc["risk"]           # proxycheck: VPN 50 > hosting 33


def test_residential_proxy_maxes_out():
    e = ip_score.evaluate({"is_proxy": True, "is_datacenter": False}, "US")
    assert e["type"] == "residential-proxy" and e["risk"] == 100
    assert e["verdict"] == "ban-risk"


def test_vpn_is_ban_risk():
    e = ip_score.evaluate({"is_vpn": True}, "US")
    assert e["verdict"] == "ban-risk" and e["proxy"] == "yes"


def test_tor_high():
    c = ip_score.classify({"is_tor": True})
    assert c["risk"] >= 75 and c["type"] == "tor"


def test_abuser_tiers():
    low = ip_score.classify({"abuser_score": 0.006})
    high = ip_score.classify({"abuser_score": 0.25})
    assert high["risk"] > low["risk"]


def test_china_residential_not_safe():
    e = ip_score.evaluate({"is_datacenter": False}, "CN")
    assert e["verdict"] == "caution" and e["region"] is True
    assert e["score"] <= 40


def test_sanctioned_is_ban_risk():
    e = ip_score.evaluate({"is_datacenter": False}, "IR")
    assert e["verdict"] == "ban-risk" and e["score"] <= 5


def test_china_plus_bad_ip_escalates():
    e = ip_score.evaluate({"is_vpn": True}, "CN")
    assert e["verdict"] == "ban-risk"
