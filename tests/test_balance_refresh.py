"""Billing-probe parsing + balance math, with urllib stubbed out."""
import time

from claude_statusbar import _balance_refresh as br
from claude_statusbar import balance_cache


def _stub_responses(monkeypatch, mapping):
    """mapping: dict of url-substring -> json dict (or None for 404/error)."""
    def fake_get(url, token):
        for needle, resp in mapping.items():
            if needle in url:
                return resp
        return None
    monkeypatch.setattr(br, "_get_json", fake_get)


def test_probe_computes_balance_cents_convention(monkeypatch):
    _stub_responses(monkeypatch, {
        "/v1/dashboard/billing/subscription": {"hard_limit_usd": 810},
        "/v1/dashboard/billing/usage": {"object": "list", "total_usage": 3.0719},
    })
    out = br._probe("https://relay.example", "sk-x")
    assert out["total"] == 810.0
    # total_usage is in cents → /100
    assert out["used"] == 0.0307
    assert out["balance"] == 809.9693
    assert out["currency"] == "USD"


def test_probe_falls_back_to_system_hard_limit(monkeypatch):
    _stub_responses(monkeypatch, {
        "/v1/dashboard/billing/subscription":
            {"system_hard_limit_usd": 100},
        "/v1/dashboard/billing/usage": {"total_usage": 0},
    })
    out = br._probe("https://relay.example", "sk-x")
    assert out["total"] == 100.0
    assert out["balance"] == 100.0


def test_probe_missing_usage_means_zero_used(monkeypatch):
    _stub_responses(monkeypatch, {
        "/v1/dashboard/billing/subscription": {"hard_limit_usd": 50},
        # no usage endpoint
    })
    out = br._probe("https://relay.example", "sk-x")
    assert out["used"] == 0.0
    assert out["balance"] == 50.0


def test_probe_tries_root_prefix_when_v1_absent(monkeypatch):
    _stub_responses(monkeypatch, {
        "/dashboard/billing/subscription": {"hard_limit_usd": 20},
        "/dashboard/billing/usage": {"total_usage": 500},  # $5
    })
    # the /v1 variants return None, so it must fall through to the root prefix
    out = br._probe("https://relay.example", "sk-x")
    assert out["total"] == 20.0
    assert out["used"] == 5.0
    assert out["balance"] == 15.0


def test_probe_unsupported_returns_none(monkeypatch):
    _stub_responses(monkeypatch, {})  # everything 404s
    assert br._probe("https://api.anthropic.com", "sk-x") is None


def test_probe_subscription_without_limit_is_unsupported(monkeypatch):
    _stub_responses(monkeypatch, {
        "/v1/dashboard/billing/subscription": {"object": "x"},  # no *_usd field
    })
    assert br._probe("https://relay.example", "sk-x") is None


def test_main_writes_supported_cache_and_clears_inflight(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    _stub_responses(monkeypatch, {
        "/v1/dashboard/billing/subscription": {"hard_limit_usd": 7},
        "/v1/dashboard/billing/usage": {"total_usage": 100},
    })
    fp = balance_cache.fingerprint("https://relay.example", "sk-x")
    monkeypatch.setenv("CS_BALANCE_FP", fp)
    monkeypatch.setenv("CS_BALANCE_KEY", "sk-x")
    balance_cache.mark_inflight(fp)
    br.main(["_balance_refresh", "https://relay.example"])
    entry = balance_cache.read_cache(fp)
    assert entry["supported"] is True
    assert entry["balance"] == 6.0
    assert balance_cache.is_inflight(fp) is False


def test_main_records_unsupported_for_404_relay(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    _stub_responses(monkeypatch, {})
    fp = balance_cache.fingerprint("https://api.anthropic.com", "sk-x")
    monkeypatch.setenv("CS_BALANCE_FP", fp)
    monkeypatch.setenv("CS_BALANCE_KEY", "sk-x")
    br.main(["_balance_refresh", "https://api.anthropic.com"])
    entry = balance_cache.read_cache(fp)
    assert entry["supported"] is False
    # negative entry is considered fresh for the long TTL
    assert balance_cache.is_fresh(entry) is True
