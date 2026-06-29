"""relay_balance_text gating + the no-quota balance segment in each style."""
import time

from claude_statusbar import balance_cache, core, progress, styles


def _env(base="https://relay.example", key="sk-x"):
    e = {}
    if base:
        e["ANTHROPIC_BASE_URL"] = base
    if key:
        e["ANTHROPIC_API_KEY"] = key
    return e


def test_balance_text_empty_without_base_or_key():
    assert core.relay_balance_text({}, spawn=False) == ""
    assert core.relay_balance_text(_env(base=None), spawn=False) == ""
    assert core.relay_balance_text(_env(key=None), spawn=False) == ""


def test_balance_text_from_fresh_supported_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    env = _env()
    fp = balance_cache.fingerprint(env["ANTHROPIC_BASE_URL"], env["ANTHROPIC_API_KEY"])
    balance_cache.write_cache_atomic(
        fp, {"ts": time.time(), "supported": True, "balance": 809.9693})
    assert core.relay_balance_text(env, spawn=False) == "bal $809.97"


def test_balance_text_hidden_for_unsupported_relay(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    env = _env()
    fp = balance_cache.fingerprint(env["ANTHROPIC_BASE_URL"], env["ANTHROPIC_API_KEY"])
    balance_cache.write_cache_atomic(
        fp, {"ts": time.time(), "supported": False})
    # fresh negative cache → no segment, and (crucially) no re-spawn
    assert core.relay_balance_text(env, spawn=False) == ""


def test_balance_text_thousands_separator(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    env = _env()
    fp = balance_cache.fingerprint(env["ANTHROPIC_BASE_URL"], env["ANTHROPIC_API_KEY"])
    balance_cache.write_cache_atomic(
        fp, {"ts": time.time(), "supported": True, "balance": 1234.5})
    assert core.relay_balance_text(env, spawn=False) == "bal $1,234.50"


def test_no_spawn_when_spawn_false(tmp_path, monkeypatch):
    """spawn=False (suppressed side effects) must never launch a subprocess."""
    monkeypatch.setenv("HOME", str(tmp_path))
    import subprocess
    monkeypatch.setattr(subprocess, "Popen",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("spawned")))
    assert core.relay_balance_text(_env(), spawn=False) == ""


# --- the segment renders in each no-quota style ---

def test_classic_balance_segment():
    out = progress.format_status_line(
        msgs_pct=None, tkns_pct=None, reset_time="--", model="qwen-max",
        ctx_pct=0, no_quota=True, balance_text="bal $809.97", use_color=False)
    assert "bal $809.97" in out
    assert "qwen-max" in out


def test_capsule_balance_segment():
    out = styles.render_capsule(
        msgs_pct=None, weekly_pct=None, reset_5h="--", reset_7d="",
        model="qwen-max", ctx_pct=0, no_quota=True,
        balance_text="bal $809.97", use_color=False)
    assert "bal $809.97" in out


def test_hairline_balance_segment():
    out = styles.render_hairline(
        msgs_pct=None, weekly_pct=None, reset_5h="--", reset_7d="",
        model="qwen-max", ctx_pct=0, no_quota=True,
        balance_text="bal $809.97", use_color=False)
    assert "bal $809.97" in out


def test_no_balance_segment_when_empty():
    out = progress.format_status_line(
        msgs_pct=None, tkns_pct=None, reset_time="--", model="qwen-max",
        ctx_pct=0, no_quota=True, balance_text="", use_color=False)
    assert "bal" not in out
