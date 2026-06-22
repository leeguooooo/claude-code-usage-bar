"""Unit tests for no-quota-mode detection (core.is_no_quota_mode).

No-quota mode = the official 5h/7d rate-limit quota is structurally
unavailable, so the bar should drop the quota battery bars and promote
context instead. Triggered by third-party relays (ANTHROPIC_BASE_URL
pointing off api.anthropic.com) and cloud backends (Bedrock/Vertex),
mirroring claude-hud's shouldHideUsage.

Detection is a pure function of the process environment + an explicit
override, so these tests feed env dicts directly.
"""

from claude_statusbar import core


def test_relay_base_url_triggers_no_quota():
    """ANTHROPIC_BASE_URL pointing at a third-party relay → no-quota mode."""
    assert core.is_no_quota_mode({"ANTHROPIC_BASE_URL": "https://relay.example.com"}) is True


def test_official_base_url_does_not_trigger():
    """The real Anthropic endpoint is NOT a relay — quota is available."""
    assert core.is_no_quota_mode({"ANTHROPIC_BASE_URL": "https://api.anthropic.com"}) is False
    # trailing slash / path variations on the official host still count as official
    assert core.is_no_quota_mode({"ANTHROPIC_BASE_URL": "https://api.anthropic.com/v1"}) is False


def test_empty_env_does_not_trigger():
    """Plain official subscription: no ANTHROPIC_* vars → normal layout."""
    assert core.is_no_quota_mode({}) is False


def test_bedrock_triggers_no_quota():
    assert core.is_no_quota_mode({"CLAUDE_CODE_USE_BEDROCK": "1"}) is True


def test_vertex_triggers_no_quota():
    assert core.is_no_quota_mode({"CLAUDE_CODE_USE_VERTEX": "1"}) is True


def test_bedrock_zero_does_not_trigger():
    """An explicit disable (=0) must not be read as enabled."""
    assert core.is_no_quota_mode({"CLAUDE_CODE_USE_BEDROCK": "0"}) is False


def test_override_off_forces_normal():
    """override='off' wins even when env looks like a relay."""
    assert core.is_no_quota_mode(
        {"ANTHROPIC_BASE_URL": "https://relay.example.com"}, override="off"
    ) is False


def test_override_on_forces_no_quota():
    """override='on' wins even on a plain official environment."""
    assert core.is_no_quota_mode({}, override="on") is True


# --- heuristic fallback (core._no_quota_heuristic) ---
# Insurance for when ANTHROPIC_BASE_URL isn't inherited by the statusLine
# subprocess: if the transcript already has an assistant response yet no quota
# ever arrived (live or cached), the headers are being stripped → no-quota.

def test_heuristic_fires_when_assistant_present_but_no_quota():
    data = {"_has_stdin": True, "rate_limit_pct": None, "rate_limit_7d_pct": None}
    assert core._no_quota_heuristic(data, transcript_has_assistant=True) is True


def test_heuristic_silent_before_first_response():
    """Session just started, no assistant turn yet → don't prematurely switch."""
    data = {"_has_stdin": True, "rate_limit_pct": None, "rate_limit_7d_pct": None}
    assert core._no_quota_heuristic(data, transcript_has_assistant=False) is False


def test_heuristic_silent_when_quota_present():
    """Official session (live or cached quota) → never heuristic, even with turns."""
    data = {"_has_stdin": True, "rate_limit_pct": 42, "rate_limit_7d_pct": None}
    assert core._no_quota_heuristic(data, transcript_has_assistant=True) is False


def test_heuristic_silent_without_stdin():
    data = {"rate_limit_pct": None, "rate_limit_7d_pct": None}
    assert core._no_quota_heuristic(data, transcript_has_assistant=True) is False
