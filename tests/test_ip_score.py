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


def test_ban_threshold_aligns_with_crit_band():
    # risk 67-69 must NOT read as ban-risk on a non-anonymizer type — the
    # ban-risk cutoff (70) has to match classify()'s crit band (also 70).
    assert ip_score.verdict(69, "hosting", "US")["verdict"] == "caution"
    assert ip_score.verdict(70, "hosting", "US")["verdict"] == "ban-risk"


def test_china_cloud_by_org_flagged_even_on_us_ip():
    # Aliyun node geolocating to the US: flagged by provider org, not IP geo.
    e = ip_score.evaluate({"is_datacenter": True, "org": "Alibaba (US) Technology Co."}, "US")
    assert e["china_cloud"] is True
    assert e["risk"] == 33 + 25            # hosting + china-cloud
    assert e["score"] <= 42               # notably worse than a neutral US DC (60)


def test_china_cloud_by_asn():
    e = ip_score.evaluate({"is_datacenter": True, "asn": 45102}, "US")  # Alibaba
    assert e["china_cloud"] is True and e["risk"] == 58


def test_cn_residential_isp_is_not_china_cloud():
    # CN-registered but NOT hosting → a normal residential ISP, not a cloud.
    c = ip_score.classify({"is_datacenter": False, "org": "China Telecom, CN"})
    assert c["china_cloud"] is False and c["type"] == "residential"


def test_neutral_datacenter_is_not_china_cloud():
    e = ip_score.evaluate({"is_datacenter": True, "org": "Amazon AWS", "asn": 16509}, "US")
    assert e["china_cloud"] is False and e["risk"] == 33
