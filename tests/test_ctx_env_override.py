"""Issue #29: CLAUDE_CODE_AUTO_COMPACT_WINDOW / CLAUDE_CODE_DISABLE_1M_CONTEXT
must override the stdin-reported context window size.

Claude Code honors these env vars for auto-compact, but the statusLine stdin
keeps reporting the stock size — so cs must re-derive ctx% against the real
window. Empty/invalid env values fall back to current behavior (stdin size).

`_context_window_usage` takes an explicit `env` mapping (the daemon path
passes the per-session env), so most tests feed a plain dict. Keys absent
from that mapping fall back to os.environ (render_thin doesn't stamp these
vars into `_cs_env`), so the fixture below scrubs the real environment.
"""

import pytest

from claude_statusbar import core


@pytest.fixture(autouse=True)
def _scrub_real_env(monkeypatch):
    """Keep the developer's / CI's real env vars out of the fallback path."""
    monkeypatch.delenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_DISABLE_1M_CONTEXT", raising=False)


def _usage(stdin_data, env):
    return core._context_window_usage(stdin_data, env=env)


# --- CLAUDE_CODE_AUTO_COMPACT_WINDOW -----------------------------------------

def test_auto_compact_window_rescales_pct():
    # stdin says 50% of 200K (=100K used); the real window is 400K → 25%.
    ctx_pct, ctx_size, ctx_used = _usage(
        {"context_window_size": 200_000, "context_used_pct": 50},
        env={"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "400000"},
    )
    assert ctx_size == 400_000
    assert ctx_used == 100_000
    assert ctx_pct == 25.0


def test_auto_compact_window_equal_to_reported_is_noop():
    ctx_pct, ctx_size, ctx_used = _usage(
        {"context_window_size": 200_000, "context_used_pct": 50},
        env={"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "200000"},
    )
    assert (ctx_pct, ctx_size, ctx_used) == (50.0, 200_000, 100_000)


def test_auto_compact_window_smaller_than_reported_also_wins():
    # A user can force a SMALLER effective window too; pct scales up.
    ctx_pct, ctx_size, ctx_used = _usage(
        {"context_window_size": 200_000, "context_used_pct": 25},
        env={"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "100000"},
    )
    assert ctx_size == 100_000
    assert ctx_used == 50_000
    assert ctx_pct == 50.0


def test_invalid_values_fall_back_to_stdin_size():
    for bad in ("", "  ", "abc", "-5", "0", "40e4"):
        ctx_pct, ctx_size, ctx_used = _usage(
            {"context_window_size": 200_000, "context_used_pct": 50},
            env={"CLAUDE_CODE_AUTO_COMPACT_WINDOW": bad},
        )
        assert (ctx_pct, ctx_size, ctx_used) == (50.0, 200_000, 100_000), bad


def test_env_without_the_vars_is_current_behavior():
    ctx_pct, ctx_size, ctx_used = _usage(
        {"context_window_size": 200_000, "context_used_pct": 50}, env={})
    assert (ctx_pct, ctx_size, ctx_used) == (50.0, 200_000, 100_000)


def test_no_stdin_context_stays_hidden_even_with_env():
    # No context_window in stdin → no segment; env alone must not invent one.
    assert _usage({}, env={"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "400000"}) \
        == (None, 0, 0)


def test_null_pct_keeps_token_fallback_and_overridden_size():
    ctx_pct, ctx_size, ctx_used = _usage(
        {"context_window_size": 200_000, "context_used_pct": None,
         "total_input_tokens": 1200, "total_output_tokens": 34},
        env={"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "400000"},
    )
    assert ctx_pct is None          # unknown stays unknown
    assert ctx_size == 400_000      # but the window itself is corrected
    assert ctx_used == 1234


# --- CLAUDE_CODE_DISABLE_1M_CONTEXT ------------------------------------------

def test_disable_1m_caps_reported_1m_back_to_200k():
    # stdin says 10% of 1M (=100K used); 1M is disabled → 50% of 200K.
    ctx_pct, ctx_size, ctx_used = _usage(
        {"context_window_size": 1_000_000, "context_used_pct": 10},
        env={"CLAUDE_CODE_DISABLE_1M_CONTEXT": "1"},
    )
    assert ctx_size == 200_000
    assert ctx_used == 100_000
    assert ctx_pct == 50.0


def test_disable_1m_leaves_stock_window_alone():
    ctx_pct, ctx_size, ctx_used = _usage(
        {"context_window_size": 200_000, "context_used_pct": 50},
        env={"CLAUDE_CODE_DISABLE_1M_CONTEXT": "true"},
    )
    assert (ctx_pct, ctx_size, ctx_used) == (50.0, 200_000, 100_000)


def test_disable_1m_falsy_spellings_are_ignored():
    for off in ("", "0", "false", "no"):
        _, ctx_size, _ = _usage(
            {"context_window_size": 1_000_000, "context_used_pct": 10},
            env={"CLAUDE_CODE_DISABLE_1M_CONTEXT": off},
        )
        assert ctx_size == 1_000_000, off


def test_auto_compact_window_wins_over_disable_1m():
    # Both set (the exact combo from #29): the explicit size wins.
    ctx_pct, ctx_size, ctx_used = _usage(
        {"context_window_size": 200_000, "context_used_pct": 50},
        env={"CLAUDE_CODE_DISABLE_1M_CONTEXT": "1",
             "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "400000"},
    )
    assert ctx_size == 400_000
    assert ctx_pct == 25.0


# --- default env source -------------------------------------------------------

def test_default_env_is_os_environ(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "400000")
    ctx_pct, ctx_size, _ = core._context_window_usage(
        {"context_window_size": 200_000, "context_used_pct": 50})
    assert ctx_size == 400_000
    assert ctx_pct == 25.0


def test_session_env_missing_key_falls_back_to_os_environ(monkeypatch):
    # Daemon path: render_thin's stamped _cs_env doesn't carry these vars, but
    # the daemon's inherited os.environ does — the override must still apply.
    monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "400000")
    ctx_pct, ctx_size, _ = _usage(
        {"context_window_size": 200_000, "context_used_pct": 50},
        env={"CS_API_MODE": "auto"},
    )
    assert ctx_size == 400_000
    assert ctx_pct == 25.0


def test_session_env_value_wins_over_os_environ(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "800000")
    _, ctx_size, _ = _usage(
        {"context_window_size": 200_000, "context_used_pct": 50},
        env={"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "400000"},
    )
    assert ctx_size == 400_000


def test_override_helper_rejects_garbage_directly():
    assert core._env_context_window_override(
        200_000, {"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "nope"}) is None
    assert core._env_context_window_override(200_000, {}) is None
    assert core._env_context_window_override(
        1_000_000, {"CLAUDE_CODE_DISABLE_1M_CONTEXT": "on"}) == 200_000
