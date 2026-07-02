#!/usr/bin/env python3
"""
Claude Code Status Bar Monitor - Final Fixed Version
Resolves dependency issues, ensuring operation in any environment
"""

import json
import sys
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Heavy stdlib imports (logging, subprocess, shutil, re) are deferred to
# the functions that use them — they collectively cost ~12ms at import time
# and most are only touched on the slow analysis path (claude-monitor
# subprocess, error logging) or in occasional model-string cleanup.

# Module-local logger handle. We only build it on first use; the import
# itself was costing ~2ms even though most renders never log anything.
_logger = None

def _get_logger():
    global _logger
    if _logger is None:
        import logging
        _logger = logging.getLogger(__name__)
        _logger.setLevel(logging.ERROR)
        _logger.addHandler(logging.NullHandler())
    return _logger


def parse_stdin_data() -> Dict[str, Any]:
    """Parse JSON data injected by Claude Code via stdin.

    Claude Code sends rich session data including model, cost, context window,
    and (for Pro/Max) rate limits.  We extract everything useful so the
    statusbar can display official numbers without spawning subprocesses.
    """
    result: Dict[str, Any] = {}
    try:
        if sys.stdin.isatty():
            return result
        raw = sys.stdin.read()
        if not raw:
            return result

        debug_file = Path.home() / ".cache" / "claude-statusbar" / "last_stdin.json"
        data = json.loads(raw)
        # Mark stdin as valid the moment we parse it. If any per-field
        # extraction below raises (e.g. Anthropic ships an unexpected shape),
        # main() must still take the "have stdin" branch and render with the
        # partial data we managed to extract — not silently fall back to the
        # "no stdin" path.
        result['_has_stdin'] = True

        # Per-session env stamped by render_thin (`_cs_env`): the shared daemon's
        # os.environ is frozen at its own start and is NOT this session's, so
        # no-quota detection must read this instead of os.environ when present.
        session_env = data.get('_cs_env')
        if isinstance(session_env, dict):
            result['_session_env'] = {str(k): str(v)
                                      for k, v in session_env.items()}
            _env = result['_session_env']
        else:
            _env = os.environ

        # Only cache stdin when it contains rate_limits (avoid overwriting with empty data).
        # Skip when the environment is a relay/cloud backend: a relay that happens
        # to forward a five_hour object would otherwise get cached as official-looking
        # quota and later suppress no-quota detection. Atomic write — Ctrl+C must
        # not corrupt the cache.
        if data.get('rate_limits', {}).get('five_hour') and not is_no_quota_mode(_env):
            from .cache import atomic_write_text
            atomic_write_text(debug_file, raw)

        # Session ID
        result['session_id'] = data.get('session_id', '')

        # Transcript path — used by the prompt-cache countdown and the
        # optional live-activity line (todos / active tool / agents).
        result['transcript_path'] = data.get('transcript_path', '')

        # Model
        model_obj = data.get('model', {})
        if isinstance(model_obj, dict):
            result['model_id'] = model_obj.get('id', '')
            result['display_name'] = model_obj.get('display_name', '')

        # Session-mode readout (the ⚙ line): effort level, thinking on/off,
        # fast mode, output style — all from Claude Code's stdin. Each guarded so
        # an older Claude Code that omits a field just drops that segment.
        effort_obj = data.get('effort', {})
        if isinstance(effort_obj, dict):
            result['effort_level'] = str(effort_obj.get('level', '') or '')
        thinking_obj = data.get('thinking', {})
        if isinstance(thinking_obj, dict) and 'enabled' in thinking_obj:
            result['thinking_enabled'] = bool(thinking_obj.get('enabled'))
        if 'fast_mode' in data:
            result['fast_mode'] = bool(data.get('fast_mode'))
        style_obj = data.get('output_style', {})
        if isinstance(style_obj, dict):
            result['output_style'] = str(style_obj.get('name', '') or '')

        # Rate limits (Claude.ai Pro/Max only)
        # Coerce percentages to int and clamp to [0, ∞):
        # - Anthropic occasionally returns floats like 56.00000000000001
        # - Reject NaN/inf so they never reach the renderer
        # - Clamp negatives to 0 (defensive — should never happen in practice)
        # - Don't cap at 100; values >100% are valid for over-quota indicators
        import math
        import time as _time
        # No real quota percentage reaches this; an implausibly large value is
        # the known upstream leak where used_percentage carries the reset epoch
        # (~1.78e9). Reject it rather than render a spurious MAX bar.
        PCT_LEAK_CEILING = 100000
        def _pct(v):
            try:
                f = float(v)
            except (TypeError, ValueError):
                return 0
            if math.isnan(f) or math.isinf(f):
                return 0
            if f >= PCT_LEAK_CEILING:
                return 0
            return max(0, int(round(f)))

        # Time-based window rollover (cached-fallback only).
        # Anthropic only pushes fresh rate_limits when the user actually
        # makes a request. Fresh stdin we trust verbatim — comparing its
        # resets_at against local clock can spuriously zero out a still-
        # valid window on a 1-second boundary, which makes the statusbar
        # flip between the real pct and 0% across renders.
        #
        # For the cached fallback path, if resets_at is in the past the
        # old window has rolled over and the cached pct is meaningless;
        # signal "unknown" (None) so the renderer shows "--", not a
        # bogus authoritative 0%.
        FIVE_HOUR_S  = 5 * 3600
        SEVEN_DAY_S  = 7 * 86400
        # Don't fall back to a stale cache; if no session has refreshed
        # last_stdin.json in this long, assume we don't know the value.
        # 10 min covers low-frequency status-bar pollers (some tmux/i3bar
        # configs refresh every several minutes) without re-introducing
        # the multi-session contention window.
        LAST_STDIN_FALLBACK_MAX_AGE_S = 600

        def _rollover_cached(pct, resets_at, window_s):
            try:
                resets_at_f = float(resets_at) if resets_at is not None else None
            except (TypeError, ValueError):
                return pct, resets_at
            if resets_at_f is None:
                return pct, resets_at
            if resets_at_f > _time.time():
                return pct, resets_at  # current window still active
            # Window expired — pct is unknown until fresh data arrives.
            elapsed = _time.time() - resets_at_f
            windows_passed = int(elapsed // window_s) + 1
            return None, int(resets_at_f + windows_passed * window_s)
        rl = data.get('rate_limits', {})
        fh = rl.get('five_hour', {})
        if fh:
            # Trust Anthropic's fresh values verbatim.
            result['rate_limit_pct'] = _pct(fh.get('used_percentage', 0))
            result['rate_limit_resets_at'] = fh.get('resets_at')
        sd = rl.get('seven_day', {})
        if sd:
            result['rate_limit_7d_pct'] = _pct(sd.get('used_percentage', 0))
            result['rate_limit_7d_resets_at'] = sd.get('resets_at')

        # Fallback: load rate_limits from previous session's cached stdin,
        # but only if the cache is fresh enough to be trustworthy.
        if not fh and not sd:
            try:
                if _time.time() - debug_file.stat().st_mtime > LAST_STDIN_FALLBACK_MAX_AGE_S:
                    raise OSError("cache too old")
                cached = json.loads(debug_file.read_text(encoding="utf-8"))
                cached_rl = cached.get('rate_limits', {})
                cached_fh = cached_rl.get('five_hour', {})
                cached_sd = cached_rl.get('seven_day', {})
                if cached_fh:
                    p, ra = _rollover_cached(_pct(cached_fh.get('used_percentage', 0)),
                                       cached_fh.get('resets_at'), FIVE_HOUR_S)
                    result['rate_limit_pct'] = p
                    result['rate_limit_resets_at'] = ra
                if cached_sd:
                    p, ra = _rollover_cached(_pct(cached_sd.get('used_percentage', 0)),
                                       cached_sd.get('resets_at'), SEVEN_DAY_S)
                    result['rate_limit_7d_pct'] = p
                    result['rate_limit_7d_resets_at'] = ra
            except (OSError, json.JSONDecodeError, TypeError):
                pass

        # Context window
        cw = data.get('context_window', {})
        if cw:
            result['context_used_pct'] = cw.get('used_percentage', 0)
            result['context_remaining_pct'] = cw.get('remaining_percentage', 100)
            result['context_window_size'] = cw.get('context_window_size', 0)
            result['total_input_tokens'] = cw.get('total_input_tokens', 0)
            result['total_output_tokens'] = cw.get('total_output_tokens', 0)

        # Session cost
        cost = data.get('cost', {})
        if cost:
            result['session_cost_usd'] = cost.get('total_cost_usd', 0.0)
            result['total_duration_ms'] = cost.get('total_duration_ms', 0)
            result['lines_added'] = cost.get('total_lines_added', 0)
            result['lines_removed'] = cost.get('total_lines_removed', 0)

        # Version
        result['claude_version'] = data.get('version', '')

        # Workspace identity (used by the optional project/branch segment).
        ws = data.get('workspace') or {}
        if isinstance(ws, dict):
            result['workspace_current_dir'] = ws.get('current_dir') or data.get('cwd')
            result['workspace_project_dir'] = ws.get('project_dir')
            result['workspace_git_worktree'] = ws.get('git_worktree')
            repo_obj = ws.get('repo') or {}
            if isinstance(repo_obj, dict):
                result['workspace_repo_name'] = repo_obj.get('name')

    except json.JSONDecodeError:
        # Bad JSON from stdin — treat as if there was no stdin at all.
        result.pop('_has_stdin', None)
    except (TypeError, AttributeError):
        # Unexpected shape on a sub-field; preserve _has_stdin so main()
        # still renders with whatever we managed to extract.
        pass
    return result


_OFFICIAL_API_HOST = "api.anthropic.com"
# Claude Code began emitting official rate_limits around this version. Below it,
# an official subscription session legitimately has no rate_limits — so the
# no-quota heuristic must NOT fire there (it would misread an old-client official
# user as a relay). See _claude_emits_rate_limits / _no_quota_heuristic.
_RATE_LIMITS_MIN_VERSION = (2, 1, 80)


def _env_truthy(value) -> bool:
    """True for the usual truthy env spellings (handles '1\\n', 'true', ' ON ')."""
    return str(value).strip().lower() in {"1", "true", "yes", "on", "y", "t"}


def _leading_int(token: str) -> int:
    digits = ""
    for ch in str(token):
        if ch.isdigit():
            digits += ch
        else:
            break
    return int(digits) if digits else 0


def _claude_emits_rate_limits(version) -> bool:
    """True when `version` (Claude Code's reported version) is new enough to emit
    official rate_limits. Tolerates suffixes ('2.1.80-beta') and junk (→ False)."""
    if not version:
        return False
    parts = tuple(_leading_int(p) for p in str(version).split(".")[:3])
    parts = parts + (0,) * (3 - len(parts))
    return parts >= _RATE_LIMITS_MIN_VERSION


def is_no_quota_mode(env: Dict[str, str], *, override: str = "auto") -> bool:
    """Return True when official 5h/7d rate-limit quota is structurally absent.

    Triggered by third-party relays (``ANTHROPIC_BASE_URL`` pointing off
    ``api.anthropic.com``) and cloud backends (Bedrock / Vertex), mirroring
    claude-hud's ``shouldHideUsage``. In that case the bar drops the quota
    battery bars and promotes the context window instead.

    Pure function of the process environment plus an explicit override
    (``auto`` / ``on`` / ``off``) so it stays trivially testable. The env
    signal is stable from session start, so it never false-positives the
    "session just started, quota not pushed yet" case the way a bare
    "no rate_limits" check would.
    """
    if override == "on":
        return True
    if override == "off":
        return False

    base = (env.get("ANTHROPIC_BASE_URL") or "").strip()
    if base:
        from urllib.parse import urlparse
        # Add a "//" authority prefix when there's no scheme, so urlparse pulls
        # the host out instead of treating the whole value as a path. Then compare
        # the parsed host EXACTLY (case-insensitive, trailing dot stripped) — a
        # raw substring check misreads "API.ANTHROPIC.COM" and lets look-alikes
        # like "notapi.anthropic.com.evil" pass as official.
        parsed = urlparse(base if "//" in base else "//" + base)
        host = (parsed.hostname or "").strip().rstrip(".").lower()
        if host != _OFFICIAL_API_HOST:
            return True

    if _env_truthy(env.get("CLAUDE_CODE_USE_BEDROCK")):
        return True
    if _env_truthy(env.get("CLAUDE_CODE_USE_VERTEX")):
        return True

    return False


def _no_quota_heuristic(stdin_data: Dict[str, Any], *,
                        transcript_has_assistant: bool,
                        claude_version_ok: bool = True) -> bool:
    """Fallback no-quota detection for when the env signal is absent.

    Insurance for the case where ``ANTHROPIC_BASE_URL`` is set but not inherited
    by the statusLine subprocess. An official session gets ``rate_limits`` in
    stdin the moment it has made an API call, and cs caches it — so once an
    assistant response exists in the transcript, an official session would have
    quota (live or cached). If a response exists yet quota is still entirely
    absent, the headers are being stripped by a relay → no-quota mode.

    ``claude_version_ok`` gates this on a Claude Code version that actually emits
    rate_limits: on an OLD client an official subscription legitimately has no
    rate_limits, and must NOT be misread as a relay — it keeps the existing
    waiting/old-client layout instead. Only fires when there's also already an
    assistant turn, so a brand-new session is never misclassified. Callers gate
    on api_mode != 'off' and a prior env-detection miss.
    """
    if not claude_version_ok:
        return False
    if not stdin_data.get('_has_stdin'):
        return False
    if stdin_data.get('rate_limit_pct') is not None:
        return False
    if stdin_data.get('rate_limit_7d_pct') is not None:
        return False
    return transcript_has_assistant


def _transcript_has_assistant(transcript_path: str) -> bool:
    """True when the transcript carries at least one assistant response.

    Reuses ``_last_assistant_info`` (a bounded tail scan, already used for the
    prompt-cache countdown), which returns None when no assistant entry exists.
    """
    if not transcript_path:
        return False
    try:
        return _last_assistant_info(transcript_path) is not None
    except Exception:
        return False


def _format_balance(entry: dict) -> str:
    """Render a fresh, supported balance cache entry as ``bal $809.97``.

    Two decimals always — at relay scale the cents are small but a bare
    ``$810`` would hide that you've already burned into it. Returns "" for a
    malformed entry so the caller can simply drop the segment.
    """
    bal = entry.get("balance")
    if not isinstance(bal, (int, float)):
        return ""
    return f"bal ${bal:,.2f}"


def _balance_remaining_pct(entry: dict):
    """Remaining-balance percent (0–100) for the fuel-gauge battery, or None.

    Returns None when ``total`` (the relay's hard_limit) is absent or non-positive
    — some relays report a sentinel/zero limit, and a gauge off a meaningless
    total would mislead, so the caller falls back to the plain ``bal $X`` text.
    """
    total = entry.get("total")
    bal = entry.get("balance")
    if not isinstance(total, (int, float)) or total <= 0:
        return None
    if not isinstance(bal, (int, float)):
        return None
    return max(0.0, min(100.0, bal / total * 100.0))


def relay_balance(env: Dict[str, str], *, spawn: bool = True):
    """Best-effort relay account balance entry (dict) for the no-quota segment.

    Reads ``ANTHROPIC_BASE_URL`` + the bearer key from ``env``, returns the cached
    balance entry (``{balance, total, used, ...}``) when fresh & supported, and
    otherwise kicks off a detached ``_balance_refresh`` probe (when ``spawn`` and
    not already inflight). Returns None whenever there's nothing to show yet, the
    relay doesn't expose the OpenAI-compatible billing endpoints (cached
    ``supported=False``), or no base_url/key is configured — so the segment
    self-hides, matching the "show it if supported, hide if not" contract.

    Never blocks on the network: the probe always runs in a separate process,
    exactly like the git dirty-state refresh.
    """
    base = (env.get("ANTHROPIC_BASE_URL") or "").strip()
    key = (env.get("ANTHROPIC_API_KEY") or "").strip()
    auth = (env.get("ANTHROPIC_AUTH_TOKEN") or "").strip()
    if not base or not (key or auth):
        return None

    from . import balance_cache
    fp = balance_cache.fingerprint(base, key or auth)
    entry = balance_cache.read_cache(fp)
    if balance_cache.is_fresh(entry):
        return entry if entry.get("supported") else None

    if spawn and not balance_cache.is_inflight(fp):
        balance_cache.mark_inflight(fp)
        try:
            import subprocess  # lazy — keep the fresh-cache hot path import-light
            import sys
            child_env = dict(os.environ)
            child_env["CS_BALANCE_FP"] = fp
            if key:
                child_env["CS_BALANCE_KEY"] = key
            if auth:
                child_env["CS_BALANCE_AUTH"] = auth
            subprocess.Popen(
                [sys.executable, "-m", "claude_statusbar._balance_refresh", base],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                start_new_session=True,
                env=child_env,
            )
        except (OSError, ValueError):
            balance_cache.clear_inflight(fp)

    # Stale-but-supported: keep showing the last known balance while the
    # refresh runs, so the segment doesn't flicker off every TTL boundary.
    if entry and entry.get("supported"):
        return entry
    return None


def relay_balance_text(env: Dict[str, str], *, spawn: bool = True) -> str:
    """Thin string wrapper over ``relay_balance`` — ``bal $…`` or "" (back-compat)."""
    entry = relay_balance(env, spawn=spawn)
    return _format_balance(entry) if entry else ""


def is_bypass_permissions_active() -> bool:
    """Detect whether bypass-permissions mode is currently active.

    Claude Code does not expose this via the statusline stdin payload, so we
    use a best-effort multi-source approach:
      1. CLAUDE_SKIP_PERMISSIONS env var (set by some wrappers)
      2. settings.json defaultMode == 'bypassPermissions'
      3. skipDangerousModePermissionPrompt is True AND any bypass hint found
    """
    # 1. Explicit env var
    env_val = os.environ.get('CLAUDE_SKIP_PERMISSIONS', '').lower()
    if env_val in ('1', 'true', 'yes'):
        return True

    # 2. settings.json defaultMode
    try:
        settings_path = Path.home() / '.claude' / 'settings.json'
        if settings_path.exists():
            with open(settings_path, 'r', encoding='utf-8') as f:
                settings = json.load(f)
            if settings.get('defaultMode') == 'bypassPermissions':
                return True
    except Exception:
        pass

    return False


def get_current_model(stdin_data: Optional[Dict[str, Any]] = None) -> tuple[str, str]:
    """Return (model_id, display_name), using stdin data when available."""
    sd = stdin_data or {}
    model = sd.get('model_id') or 'unknown'
    display_name = sd.get('display_name') or ''
    if not display_name:
        display_name = model if model != 'unknown' else 'Unknown'
    return model, display_name

def calculate_reset_time(reset_hour: Optional[int] = None) -> str:
    """Calculate time until session reset (5-hour rolling window or custom hour)"""
    # If user pins a reset hour, honor it before any external calls
    if reset_hour is not None and 0 <= reset_hour <= 23:
        now = datetime.now()
        target = now.replace(hour=reset_hour, minute=0, second=0, microsecond=0)
        if target <= now:
            target = target + timedelta(days=1)
        diff = target - now
        total_minutes = int(diff.total_seconds() / 60)
        hours = total_minutes // 60
        mins = total_minutes % 60
        return f"{hours}h {mins:02d}m"

    try:
        import shutil
        import subprocess
        # Ask an installed claude-monitor for the session reset time.
        claude_monitor_cmd = shutil.which('claude-monitor')
        if claude_monitor_cmd:
            # Find Python interpreter
            possible_paths = [
                Path.home() / ".local/share/uv/tools/claude-monitor/bin/python",
                Path.home() / ".uv/tools/claude-monitor/bin/python",
                Path.home() / ".local/pipx/venvs/claude-monitor/bin/python",  # pipx installation
            ]
            
            claude_python = None
            for path in possible_paths:
                if path.exists():
                    claude_python = str(path)
                    break
            
            if not claude_python:
                try:
                    with open(claude_monitor_cmd, 'r') as f:
                        first_line = f.readline()
                        if first_line.startswith('#!'):
                            claude_python = first_line[2:].strip()
                except:
                    pass
            
            if claude_python:
                code = """
import json
from datetime import datetime, timedelta, timezone
try:
    from claude_monitor.data.analysis import analyze_usage
    
    result = analyze_usage(hours_back=192, quick_start=False)
    blocks = result.get('blocks', [])
    
    if blocks:
        active_blocks = [b for b in blocks if b.get('isActive', False)]
        if active_blocks:
            current_block = active_blocks[0]
            start_time = current_block.get('startTime')
            
            if start_time:
                # Parse start time
                if isinstance(start_time, str):
                    if start_time.endswith('Z'):
                        start_time = start_time[:-1] + '+00:00'
                    session_start = datetime.fromisoformat(start_time)
                else:
                    session_start = start_time
                
                # Session lasts 5 hours
                session_end = session_start + timedelta(hours=5)
                now = datetime.now(timezone.utc)
                
                if session_end > now:
                    diff = session_end - now
                    total_minutes = int(diff.total_seconds() / 60)
                    
                    if total_minutes > 60:
                        hours = total_minutes // 60
                        mins = total_minutes % 60
                        print(f"{hours}h {mins:02d}m")
                    else:
                        print(f"{total_minutes}m")
                    import sys
                    sys.exit(0)
except:
    pass
print("")
"""
                # 3s cap — this is invoked from the synchronous render path
                # in the exception fallback, so a slow claude-monitor must
                # not stall the status line. On timeout we fall through to
                # the next-2pm estimate below rather than returning empty.
                try:
                    result = subprocess.run(
                        [claude_python, '-c', code],
                        capture_output=True,
                        text=True,
                        timeout=3
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        return result.stdout.strip()
                except subprocess.TimeoutExpired:
                    pass
    except Exception:
        pass
    
    # No signal: the rolling 5h window is anchored to session start, never to a
    # 14:00 wall-clock — fabricating a "next 2 PM" countdown is wrong on every
    # host. Return the honest unknown marker instead (matches the main path's
    # "--" at the resets_at-absent branch).
    return "--"

# Auto-update is rate-limited to once per machine per day. We use the mtime
# of `last_update_check` as the timestamp — touching it before the slow
# urlopen+pip work means N concurrent new sessions only fire ONE check
# (the first one to win the touch race; the rest see a fresh mtime and skip).
_UPDATE_CHECK_INTERVAL_S = 24 * 3600


_ENSURE_STATUSLINE_INTERVAL_S = 24 * 60 * 60  # once per day


def _maybe_ensure_statusline():
    """Throttle settings.json check to once per day.

    `ensure_statusline_configured()` reads + parses settings.json on every
    render — and importing setup pulls in cache + atomic_write_text. At 1Hz
    refresh that's pure waste; settings rarely change. Use a timestamp marker
    like check_for_updates does, so the heavy imports only happen on the
    daily tick.
    """
    try:
        cache_dir = Path.home() / '.cache' / 'claude-statusbar'
        cache_dir.mkdir(parents=True, exist_ok=True)
        marker = cache_dir / 'last_statusline_check'
        if marker.exists():
            try:
                if _time_now() - marker.stat().st_mtime < _ENSURE_STATUSLINE_INTERVAL_S:
                    return
            except OSError:
                pass
        marker.touch()
    except OSError:
        pass
    try:
        from .setup import ensure_statusline_configured
        ensure_statusline_configured()
    except Exception:
        pass


def check_for_updates(session_id: str = ''):
    """Check for updates at most once per machine per 24 hours.

    Disabled by setting env CLAUDE_STATUSBAR_NO_UPDATE=1 or
    passing --no-auto-update on the CLI.

    Concurrency notes
    -----------------
    Previously this was gated by session_id, so opening 5 new Claude Code
    windows simultaneously would fire 5 parallel pip installs. The timestamp
    gate fixes that: whichever cs gets to update the timestamp first wins;
    everyone else sees a fresh marker and bails before running urlopen / pip.
    """
    env_val = os.environ.get('CLAUDE_STATUSBAR_NO_UPDATE', '').lower()
    if env_val in ('1', 'true', 'yes'):
        return

    try:
        cache_dir = Path.home() / '.cache' / 'claude-statusbar'
        cache_dir.mkdir(parents=True, exist_ok=True)
        marker = cache_dir / 'last_update_check'

        # Skip if last check was within the interval.
        if marker.exists():
            try:
                age = _time_now() - marker.stat().st_mtime
                if age < _UPDATE_CHECK_INTERVAL_S:
                    return
            except OSError:
                pass

        # Touch the marker BEFORE the slow operation. Two consequences:
        #   1. A hung urlopen/pip can't trap us in a re-trigger loop on
        #      next render — the marker is already fresh.
        #   2. Concurrent sessions that arrive a few ms later see the
        #      fresh mtime and skip. (Race window is tiny but exists; if
        #      it matters we'd switch to fcntl.flock.)
        try:
            marker.touch()
        except OSError:
            return  # if we can't even touch the marker, don't try the upgrade

        # Spawn the check+upgrade in a DETACHED subprocess — never run it
        # synchronously here. A `uv tool install --upgrade` can take tens of
        # seconds; doing it inline would freeze this render. The marker is
        # already touched above, so we won't re-trigger before the interval.
        from .updater import spawn_background_upgrade_check
        spawn_background_upgrade_check()

    except Exception:
        # Silently fail - don't interrupt main functionality
        pass


def _time_now() -> float:
    """Indirection so tests can monkeypatch."""
    import time as _t
    return _t.time()


def _context_window_usage(stdin_data: Dict[str, Any]) -> Tuple[Optional[float], int, int]:
    """Return (ctx_pct, ctx_size, ctx_used) for renderer/model suffix.

    Claude sometimes sends null for context_window.used_percentage. Treat that
    as unknown instead of falling into the expensive reset-time fallback.
    """
    raw_size = stdin_data.get('context_window_size', 0)
    try:
        ctx_size_f = float(raw_size)
    except (TypeError, ValueError):
        return None, 0, 0
    if ctx_size_f <= 0:
        return None, 0, 0

    raw_pct = stdin_data.get('context_used_pct', 0)
    try:
        ctx_pct = float(raw_pct)
    except (TypeError, ValueError):
        ctx_pct = None

    if ctx_pct is not None:
        ctx_used = int(ctx_size_f * ctx_pct / 100)
    else:
        ctx_used = (
            stdin_data.get('total_input_tokens', 0)
            + stdin_data.get('total_output_tokens', 0)
        )
    return ctx_pct, int(ctx_size_f), int(ctx_used)


def format_number(num: float) -> str:
    """Format number for detail display."""
    if num >= 1_000_000:
        return f"{num/1_000_000:.1f}M"
    elif num >= 1_000:
        return f"{num/1_000:.1f}k"
    return f"{num:.0f}"


# Reverse-tail reader tunables. 32KB per seek, capped at 10 chunks (320KB)
# so a multi-MB transcript with no assistant entries can't blow up render time.
_CACHE_AGE_CHUNK = 32 * 1024
_CACHE_AGE_MAX_BYTES = 10 * _CACHE_AGE_CHUNK
# Conservative fallback when the transcript carries no cache-write signal
# (caching disabled, or a transcript old enough to predate the
# cache_creation breakdown). Under-promising (early COLD) beats claiming a
# dead cache is warm. Anthropic's own base default is also 5 minutes.
_FALLBACK_TTL_S = 300


def _entry_age(entry: Dict[str, Any]) -> Optional[float]:
    """Seconds since this transcript entry's timestamp, or None if absent/bad."""
    ts_str = entry.get("timestamp", "")
    if not isinstance(ts_str, str) or not ts_str:
        return None
    if ts_str.endswith("Z"):
        ts_str = ts_str[:-1] + "+00:00"
    try:
        last_ts = datetime.fromisoformat(ts_str)
    except ValueError:
        return None
    # Treat naive timestamps as UTC (Claude Code convention) to avoid
    # TypeError on aware-minus-naive subtraction.
    if last_ts.tzinfo is None:
        last_ts = last_ts.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - last_ts).total_seconds()


def _entry_cache_ttl(entry: Dict[str, Any]) -> Optional[int]:
    """The prompt-cache TTL Anthropic actually applied on this turn, in seconds.

    Read from `message.usage.cache_creation`, which buckets cache-WRITE tokens
    by TTL. A nonzero `ephemeral_1h_input_tokens` means the request used a
    1-hour `cache_control` ttl; `ephemeral_5m_input_tokens` means 5 minutes.
    Returns None when this turn wrote nothing to cache (both buckets 0/absent).
    """
    msg = entry.get("message")
    if not isinstance(msg, dict):
        return None
    usage = msg.get("usage")
    if not isinstance(usage, dict):
        return None
    cc = usage.get("cache_creation")
    if not isinstance(cc, dict):
        return None
    if (cc.get("ephemeral_1h_input_tokens") or 0) > 0:
        return 3600
    if (cc.get("ephemeral_5m_input_tokens") or 0) > 0:
        return 300
    return None


def _last_assistant_info(transcript_path: str) -> Optional[Tuple[float, Optional[int]]]:
    """Return (age_seconds, detected_ttl) for the prompt-cache countdown.

    - age          ← timestamp of the NEWEST assistant entry (the most recent
                     cache touch).
    - detected_ttl ← the real TTL Anthropic applied, read from the newest
                     assistant entry that actually WROTE cache (see
                     `_entry_cache_ttl`). None if no write signal exists within
                     the byte budget (caching disabled / ancient transcript).

    age and ttl are decoupled on purpose: a final read-only turn (both buckets
    0) keeps its age but falls through to the last turn that wrote cache, so
    the detected TTL isn't erased by a turn that happened to write nothing.

    Both are gathered in ONE reverse-tail pass (32KB chunks, capped at
    _CACHE_AGE_MAX_BYTES) — these files run to many MB and the status bar
    renders on every turn. Returns as soon as both are known.
    """
    age: Optional[float] = None
    ttl: Optional[int] = None
    try:
        with open(transcript_path, "rb") as f:
            f.seek(0, 2)
            file_size = f.tell()
            if file_size == 0:
                return None
            buf = b""
            pos = file_size
            scanned = 0
            while pos > 0 and scanned < _CACHE_AGE_MAX_BYTES:
                read = min(_CACHE_AGE_CHUNK, pos)
                pos -= read
                scanned += read
                f.seek(pos)
                # Prepend the new chunk; reversal order matters — the newer
                # bytes already in `buf` are at higher offsets than what we
                # just read.
                buf = f.read(read) + buf
                lines = buf.split(b"\n")
                # Unless we've reached the file start, the first line may be
                # a partial — keep it in buf for the next iteration to stitch.
                if pos > 0:
                    buf = lines[0]
                    candidates = lines[1:]
                else:
                    buf = b""
                    candidates = lines
                for raw in reversed(candidates):
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        entry = json.loads(raw)
                    except (ValueError, json.JSONDecodeError):
                        continue
                    if entry.get("type") != "assistant":
                        continue
                    # age: first (newest) assistant entry with a usable timestamp.
                    if age is None:
                        age = _entry_age(entry)
                    # ttl: first (newest) assistant entry that wrote cache.
                    if ttl is None:
                        ttl = _entry_cache_ttl(entry)
                    if age is not None and ttl is not None:
                        return (age, ttl)
    except OSError:
        return None
    if age is None:
        return None
    return (age, ttl)


def _last_assistant_age(transcript_path: str) -> Optional[float]:
    """Age in seconds of the most recent assistant entry, or None.

    Thin wrapper over `_last_assistant_info` — kept for callers/tests that
    only need the age.
    """
    info = _last_assistant_info(transcript_path)
    return info[0] if info is not None else None


def get_cache_age_text(ttl_seconds: Optional[int] = None) -> str:
    """Return cache state as a COUNTDOWN to expiry.

    Display semantics:
      - "Xm YYs" / "Ys" — time remaining before Anthropic's prompt cache
        expires. Decreasing number = increasing urgency, matching the
        `⏰2h14m` reset countdowns elsewhere on the line.
      - "COLD"          — cache has expired (or transcript has no
        assistant entry). Next API call pays full input-token price.
      - ""              — no signal at all (no last_stdin.json or
        no transcript_path); segment hidden.

    The TTL is AUTO-DETECTED from the transcript (`_last_assistant_info`):
    Anthropic reports, on every turn, which TTL it applied to the cache write
    (5m vs 1h). That ground truth already reflects subscription-vs-API-key
    auth, ENABLE_PROMPT_CACHING_1H, FORCE_PROMPT_CACHING_5M, and the
    over-quota → 5m downgrade — so no static config can do better. When the
    transcript carries no write signal we fall back to `_FALLBACK_TTL_S`.

    `ttl_seconds` is an explicit override (testing / edge cases); production
    leaves it None so the TTL is detected. The legacy `cache_ttl_seconds`
    config is no longer consulted.

    Why countdown not elapsed: the widget exists to answer "should I send
    my next prompt before the cache dies?". A countdown answers directly;
    elapsed forces the user to mentally subtract.
    """
    cache_file = Path.home() / ".cache" / "claude-statusbar" / "last_stdin.json"

    try:
        raw = json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError, FileNotFoundError):
        return ""

    tp = raw.get("transcript_path", "")
    if not tp:
        return ""
    info = _last_assistant_info(tp)
    if info is None:
        return "COLD"
    age_s, detected_ttl = info
    # Formatting (countdown + clock-skew clamp + COLD) is shared with the
    # merged single-scan render path so both produce identical output.
    from .activity import format_cache_countdown
    return format_cache_countdown(age_s, detected_ttl, ttl_seconds)


def main(json_output: bool = False,
         reset_hour: Optional[int] = None, use_color: bool = True,
         detail: bool = False,
         warning_threshold: Optional[float] = None,
         critical_threshold: Optional[float] = None,
         style_override: Optional[str] = None,
         theme_override: Optional[str] = None,
         _suppress_side_effects: bool = False):
    """Main render entry point.

    `_suppress_side_effects` is set by the daemon mode (Phase B): when the
    long-lived daemon is doing the rendering, we don't want it firing the
    per-render auto-update / settings-repair checks (those run on their own
    cadence elsewhere, and the daemon shouldn't accidentally re-trigger them
    1Hz).
    """
    """Main function"""
    from . import config as _cfg
    # Heavier imports (.styles + .themes + .progress) happen lazily below
    # because they only matter once we actually start rendering — many
    # config-info paths return early.

    cfg = _cfg.load_config()
    # Severity thresholds resolve explicit-arg → config → default. Callers
    # (cli.py / render_thin / daemon) pass None when no flag/env was given, so
    # the persisted `cs config set warning_threshold` actually drives the bar.
    # Defensive: a malformed pair must never crash the statusLine — fall back
    # to the safe default (config set-time validation makes this unreachable
    # in practice, but the render path is load-bearing).
    from .progress import normalize_thresholds as _norm_thresh
    try:
        warning_threshold, critical_threshold = _norm_thresh(
            warning_threshold if warning_threshold is not None
            else cfg.warning_threshold,
            critical_threshold if critical_threshold is not None
            else cfg.critical_threshold,
        )
    except (ValueError, TypeError):
        warning_threshold, critical_threshold = _norm_thresh(None, None)
    chosen_style = _cfg.resolve_style(style_override, cfg)
    from .styles import is_known_style as _is_known_style, render as _render_style
    if not _is_known_style(chosen_style):
        # Unknown style → silently fall back to the safe default rather than
        # explode in the statusLine where the user can't see the error.
        chosen_style = "classic"
    from .themes import get_theme, apply_color_overrides, parse_hex_color
    from .progress import get_countdown_emoji
    chosen_theme = get_theme(_cfg.resolve_theme(theme_override, cfg))
    # Layer per-severity color overrides on top of the theme. cfg fields are
    # already canonical "#rrggbb" strings (validated at set_value time), so
    # parse_hex_color never raises here. None fields stay as the theme default.
    chosen_theme = apply_color_overrides(
        chosen_theme,
        ok=parse_hex_color(cfg.color_ok) if cfg.color_ok else None,
        warn=parse_hex_color(cfg.color_warn) if cfg.color_warn else None,
        hot=parse_hex_color(cfg.color_hot) if cfg.color_hot else None,
    )

    # Auto-compact: if terminal narrower than threshold, force hairline
    if cfg.auto_compact_width > 0 and chosen_style != "hairline":
        try:
            term_w = os.get_terminal_size().columns
            if term_w < cfg.auto_compact_width:
                chosen_style = "hairline"
        except OSError:
            pass

    stdin_data = parse_stdin_data()

    # No-quota mode (third-party relay / Bedrock / Vertex): official 5h/7d quota
    # is structurally unavailable. Suppress any cached quota that parse_stdin_data
    # may have backfilled — it belongs to a previous official session/account, not
    # this relay session — so has_official stays False and the no-quota layout
    # (context bar + activity) owns the render instead of leaking stale numbers.
    # Prefer the per-session env stamped by render_thin over os.environ: under
    # the shared daemon, os.environ is the daemon's frozen start-time env, not
    # this session's, so reading it would mis-detect no-quota mode per session.
    _session_env = stdin_data.get('_session_env')
    _effective_env = _session_env if isinstance(_session_env, dict) else os.environ
    _api_mode = _cfg.resolve_api_mode(cfg, env=_effective_env)
    no_quota = is_no_quota_mode(_effective_env, override=_api_mode)
    # Heuristic fallback only when the env signal missed (and not force-disabled):
    # an assistant turn exists yet no quota ever arrived → relay stripping headers.
    # Gated tightly (no live/cached quota) so the tail scan only runs when unsure;
    # official users keep their cached quota and skip both the scan and the switch.
    if (not no_quota and _api_mode != 'off'
            and stdin_data.get('_has_stdin')
            and stdin_data.get('rate_limit_pct') is None
            and stdin_data.get('rate_limit_7d_pct') is None):
        no_quota = _no_quota_heuristic(
            stdin_data,
            transcript_has_assistant=_transcript_has_assistant(
                stdin_data.get('transcript_path', '')),
            claude_version_ok=_claude_emits_rate_limits(
                stdin_data.get('claude_version')),
        )
    if no_quota:
        stdin_data['rate_limit_pct'] = None
        stdin_data['rate_limit_7d_pct'] = None

    if cfg.show_language:
        from .progress import format_language_body
        lang_body = format_language_body(
            str(Path.home() / ".claude" / "language-progress.json"),
        )
    else:
        lang_body = ""

    # Optional session cost segment.
    cost_text = ""
    if cfg.show_cost:
        sc = stdin_data.get("session_cost_usd")
        if isinstance(sc, (int, float)) and sc >= 0:
            cost_text = f"{sc:.2f}"

    # ONE transcript tail-scan serves BOTH the activity line and the prompt-
    # cache countdown: read_activity also returns cache_age_seconds/cache_ttl.
    # When the activity line isn't wanted, fall back to the lean early-exit
    # cache reader (get_cache_age_text) so a cache-only render stays cheap.
    _want_scan = cfg.show_todos or cfg.show_tools or cfg.show_agents
    _tp = stdin_data.get("transcript_path", "")
    activity = None
    if _want_scan and _tp:
        from .activity import read_activity
        # Runs BEFORE main()'s big try/except — guard so a scanner failure
        # degrades to "no activity line" instead of blanking the whole bar.
        try:
            activity = read_activity(_tp)
        except Exception:
            activity = None

    # Optional cache age segment — from the shared scan when we did one, else
    # the standalone reader (cache-only render, no transcript, or scan failed).
    cache_age_text = ""
    if cfg.show_cache_age:
        if activity is not None:
            from .activity import format_cache_countdown
            cache_age_text = format_cache_countdown(
                activity.cache_age_seconds, activity.cache_ttl)
        else:
            cache_age_text = get_cache_age_text()

    # Experimental bar shimmer: a phase that advances one cell per render.
    # Capped at the statusLine's ~1Hz refresh, so it's a slow step. classic only.
    shimmer_phase = None
    if cfg.bar_shimmer:
        import time as _t
        shimmer_phase = int(_t.time())

    # Cheap session stats from stdin (no transcript scan). Rendered on the
    # identity line — next to the project — rather than alone on the activity
    # line. (They therefore appear only when show_project_branch is on.)
    from .activity import format_duration_short, format_lines
    duration_text = (format_duration_short(stdin_data.get("total_duration_ms", 0))
                     if cfg.show_duration else "")
    lines_text = (format_lines(stdin_data.get("lines_added", 0),
                               stdin_data.get("lines_removed", 0))
                  if cfg.show_lines else "")

    # Optional project + branch identity segment (second line).
    identity_kwargs = {}
    if cfg.show_project_branch:
        from .identity import resolve_identity, dirty_with_async_refresh
        info = resolve_identity(stdin_data)
        dirty = dirty_with_async_refresh(info.toplevel) if info.toplevel else None
        identity_kwargs = dict(
            show_project_branch=True,
            identity=info,
            identity_dirty=dirty,
            identity_duration=duration_text,
            identity_lines=lines_text,
            identity_show_version=cfg.show_version,
        )
        # git ahead/behind reuses the same cached `git status --branch` the
        # dirty refresh just triggered — only meaningful on the identity line.
        if cfg.show_ahead_behind and info.toplevel:
            from .identity import read_ahead_behind
            ahead, behind = read_ahead_behind(info.toplevel)
            identity_kwargs["identity_ahead"] = ahead
            identity_kwargs["identity_behind"] = behind
    # Dedicated egress-IP risk warning line (only shows above the risk
    # threshold; independent of the git identity segment).
    ip_line_kwargs = {}
    if cfg.show_ip_risk:
        try:
            from .ip_risk import ip_risk_line
            ip_text, ip_level = ip_risk_line()
            if ip_text:
                ip_line_kwargs = {"ip_line_text": ip_text,
                                  "ip_line_level": ip_level}
        except Exception:
            pass

    # Optional session-mode line (⚙): effort / thinking / fast / output-style,
    # straight from stdin. Each field is omitted by the renderer when absent.
    mode_kwargs = {}
    if cfg.show_mode:
        mode_kwargs = dict(
            mode_show=True,
            mode_effort=stdin_data.get('effort_level', ''),
            mode_thinking=stdin_data.get('thinking_enabled'),
            mode_fast=stdin_data.get('fast_mode'),
            mode_style=stdin_data.get('output_style', ''),
            mode_gradient=cfg.mode_gradient,
        )

    # Optional live-activity line (3rd line): todos / active tool + rollup.
    # Subagents (show_agents) render on their own bottom line(s). Reuses the
    # single `activity` scan done above.
    activity_kwargs = {}
    if _want_scan:
        activity_kwargs = dict(
            activity=activity,
            activity_opts=dict(
                show_todos=cfg.show_todos,
                show_tools=cfg.show_tools,
                show_tool_rollup=cfg.show_tool_rollup,
                show_agents=cfg.show_agents,
            ),
        )

    try:
        if not json_output and not _suppress_side_effects:
            check_for_updates(stdin_data.get('session_id', ''))
            # Silently restore statusLine config if a Claude Code upgrade wiped
            # it. Throttled to once per day — settings.json doesn't change
            # often, and at 1Hz refresh the read+parse adds up.
            _maybe_ensure_statusline()

        has_official = (stdin_data.get('rate_limit_pct') is not None or
                        stdin_data.get('rate_limit_7d_pct') is not None)

        model_id, display_name = get_current_model(stdin_data)
        bypass = is_bypass_permissions_active()

        if no_quota and stdin_data.get('_has_stdin'):
            # 🔌 No-quota mode: third-party relay / Bedrock / Vertex. No official
            # 5h/7d quota exists, so drop the quota bars and promote the context
            # window to its own battery bar, mirroring claude-hud. Activity tail
            # (todos/tools/agents) is appended by the style renderer as usual.
            ctx_pct, ctx_size, ctx_used = _context_window_usage(stdin_data)
            model = display_name if display_name != 'Unknown' else model_id
            # Drop the redundant "(1M context)" suffix — the ctx bar IS the
            # context readout now, so we don't also append "(used/size)".
            import re as _re
            model = _re.sub(r'\s*\([^)]*context[^)]*\)', '', model)

            # Optional relay account balance — only meaningful in no-quota mode
            # (third-party relay). Self-hides when the relay exposes no billing
            # endpoint. The probe runs in a detached process (like the git
            # dirty-state refresh), so it spawns under both the inline and
            # daemon render paths — _suppress_side_effects gates the per-render
            # auto-update checks, not background data refreshes.
            #
            # When balance_bar is on AND the relay reports a usable hard_limit,
            # the segment renders as a fuel-gauge battery (fill = remaining %),
            # else it falls back to the plain `bal $X` text.
            balance_text = ""
            balance_pct = None
            balance_amount = ""
            if cfg.show_balance:
                _bentry = relay_balance(_effective_env)
                if _bentry:
                    balance_text = _format_balance(_bentry)
                    if cfg.balance_bar:
                        _rp = _balance_remaining_pct(_bentry)
                        if _rp is not None:
                            balance_pct = _rp
                            balance_amount = f"${_bentry['balance']:,.2f}"

            if json_output:
                print(json.dumps({
                    "success": True, "source": "no_quota",
                    "context": {"used_percentage": ctx_pct,
                                "context_window_size": ctx_size,
                                "used_tokens": ctx_used},
                    "balance": balance_text or None,
                    "balance_remaining_pct": balance_pct,
                    "meta": {"model": model_id, "display_name": display_name,
                             "bypass": bypass},
                }))
            else:
                print(_render_style(
                    chosen_style,
                    msgs_pct=None, weekly_pct=None,
                    reset_5h="--", reset_7d="",
                    model=model, lang_body=lang_body, cost_text=cost_text,
                    bypass=bypass, cache_age_text=cache_age_text,
                    use_color=use_color, theme=chosen_theme,
                    warning_threshold=warning_threshold,
                    critical_threshold=critical_threshold,
                    density=cfg.density, show_weekly=cfg.show_weekly,
                    ctx_pct=ctx_pct,
                    shimmer_phase=shimmer_phase,
                    no_quota=True,
                    balance_text=balance_text,
                    balance_pct=balance_pct,
                    balance_amount=balance_amount,
                    **identity_kwargs, **mode_kwargs, **ip_line_kwargs,
                    **activity_kwargs,
                ))
        elif has_official:
            # ✅ Official data from Anthropic API headers (Claude Code ≥ v2.1.80)
            msgs_pct = stdin_data.get('rate_limit_pct')
            weekly_pct = stdin_data.get('rate_limit_7d_pct')
            resets_at = stdin_data.get('rate_limit_resets_at')
            resets_at_7d = stdin_data.get('rate_limit_7d_resets_at')

            try:
                from .predict import reconcile_account
                msgs_pct, resets_at, weekly_pct, resets_at_7d = reconcile_account(
                    msgs_pct, resets_at, weekly_pct, resets_at_7d,
                    session_id=stdin_data.get('session_id') or None,
                    # parse_stdin_data flattens stdin's model.id to 'model_id'
                    model=stdin_data.get('model_id') or None,
                )
            except Exception:
                pass

            if resets_at:
                diff = datetime.fromtimestamp(resets_at, tz=timezone.utc) - datetime.now(timezone.utc)
                total_min = max(0, int(diff.total_seconds() / 60))
                minutes_to_reset = total_min
                hours, mins = total_min // 60, total_min % 60
                if hours > 0:
                    reset_time = f"{hours}h{mins:02d}m"
                else:
                    reset_time = f"{mins}m"
            else:
                reset_time = "--"
                minutes_to_reset = None

            if resets_at_7d:
                diff_7d = datetime.fromtimestamp(resets_at_7d, tz=timezone.utc) - datetime.now(timezone.utc)
                total_sec_7d = max(0, int(diff_7d.total_seconds()))
                days_7d = total_sec_7d // 86400
                hours_7d = (total_sec_7d % 86400) // 3600
                mins_7d = (total_sec_7d % 3600) // 60
                if days_7d > 0:
                    reset_time_7d = f"{days_7d}d{hours_7d:02d}h"
                elif hours_7d > 0:
                    reset_time_7d = f"{hours_7d}h{mins_7d:02d}m"
                else:
                    reset_time_7d = f"{mins_7d}m"
            else:
                reset_time_7d = ""

            model = display_name if display_name != 'Unknown' else model_id

            if json_output:
                print(json.dumps({
                    "success": True, "source": "official",
                    "rate_limits": {
                        "five_hour": {"used_percentage": msgs_pct, "reset_time": reset_time},
                        "seven_day": {"used_percentage": weekly_pct, "reset_time": reset_time_7d},
                    },
                    "meta": {"model": model_id, "display_name": display_name,
                             "reset_time": reset_time, "reset_time_7d": reset_time_7d, "bypass": bypass,
                             },
                }))
            else:
                # Append context window usage to model name: Opus 4.6(10k/1M)
                ctx_pct, ctx_size, ctx_used = _context_window_usage(stdin_data)
                if ctx_size > 0:
                    # Strip redundant size suffix like "(1M context)" from display_name
                    import re as _re
                    model = _re.sub(r'\s*\([^)]*context[^)]*\)', '', model)
                    model = f"{model}({format_number(ctx_used)}/{format_number(ctx_size)})"

                countdown = get_countdown_emoji(minutes_to_reset)

                projection_kwargs = {}
                if cfg.show_projection:
                    try:
                        import time as _t
                        from .predict import projection
                        p5, p7 = projection(
                            used_5h=msgs_pct,
                            resets_5h=resets_at,
                            used_7d=weekly_pct,
                            resets_7d=resets_at_7d,
                            now=_t.time(),
                            session_id=stdin_data.get("session_id", ""),
                        )
                        projection_kwargs = {"projection_5h": p5 or "", "projection_7d": p7 or ""}
                    except Exception:
                        projection_kwargs = {}

                forecast_kwargs = {}
                if cfg.show_forecast:
                    try:
                        import time as _t
                        from .predict import forecast
                        f5, f7 = forecast(
                            used_5h=msgs_pct,
                            resets_5h=resets_at,
                            used_7d=weekly_pct,
                            resets_7d=resets_at_7d,
                            now=_t.time(),
                        )
                        forecast_kwargs = {"forecast_5h": f5 or "", "forecast_7d": f7 or ""}
                    except Exception:
                        forecast_kwargs = {}

                print(_render_style(
                    chosen_style,
                    msgs_pct=msgs_pct, weekly_pct=weekly_pct,
                    reset_5h=reset_time, reset_7d=reset_time_7d,
                    model=model, lang_body=lang_body, cost_text=cost_text,
                    bypass=bypass, cache_age_text=cache_age_text,
                    use_color=use_color, theme=chosen_theme,
                    warning_threshold=warning_threshold,
                    critical_threshold=critical_threshold,
                    countdown_emoji=countdown,
                    density=cfg.density, show_weekly=cfg.show_weekly,
                    ctx_pct=ctx_pct,
                    shimmer_phase=shimmer_phase,
                    **projection_kwargs,
                    **forecast_kwargs,
                    **identity_kwargs, **mode_kwargs, **ip_line_kwargs,
                    **activity_kwargs,
                ))
        else:
            # No rate_limits yet — could be session start or old Claude Code
            model = display_name if display_name != 'Unknown' else model_id
            version = stdin_data.get('claude_version', '') if stdin_data.get('_has_stdin') else ''

            if stdin_data.get('_has_stdin'):
                # Have stdin but no rate_limits — session just started, OR the
                # quota pipeline broke (statusLine displaced / daemon dead) and
                # the cached windows rotted. Distinguish the two: a HEALTHY
                # subscriber session that already has an assistant turn would
                # carry rate_limits (live or cached-fresh). If instead an
                # assistant turn exists, the client emits rate_limits, yet the
                # quota cache is all-stale → the pipeline stopped feeding cs.
                # Surface "stale · restart" rather than silently blank bars
                # (the failure mode that left a Pro user staring at empty space).
                ctx_pct, ctx_size, ctx_used = _context_window_usage(stdin_data)
                quota_stale = False
                if (_claude_emits_rate_limits(stdin_data.get('claude_version'))
                        and _transcript_has_assistant(
                            stdin_data.get('transcript_path', ''))):
                    try:
                        from .predict import quota_cache_status
                        _st, _ = quota_cache_status()
                        quota_stale = (_st == "stale")
                    except Exception:
                        quota_stale = False
                if ctx_size > 0:
                    import re as _re
                    model = _re.sub(r'\s*\([^)]*context[^)]*\)', '', model)
                    model = f"{model}({format_number(ctx_used)}/{format_number(ctx_size)})"

                if json_output:
                    print(json.dumps({
                        "success": True,
                        "source": "stale" if quota_stale else "waiting",
                        "meta": {"model": model_id, "display_name": display_name,
                                 "claude_version": version, "bypass": bypass},
                    }))
                else:
                    print(_render_style(
                        chosen_style,
                        msgs_pct=None, weekly_pct=None,
                        reset_5h="--", reset_7d="",
                        model=model, lang_body=lang_body, cost_text=cost_text,
                        bypass=bypass, cache_age_text=cache_age_text,
                        use_color=use_color, theme=chosen_theme,
                        warning_threshold=warning_threshold,
                        critical_threshold=critical_threshold,
                        density=cfg.density, show_weekly=cfg.show_weekly,
                        ctx_pct=ctx_pct,
                        shimmer_phase=shimmer_phase,
                        quota_stale=quota_stale,
                        **identity_kwargs, **mode_kwargs, **ip_line_kwargs,
                        **activity_kwargs,
                    ))
            else:
                # No stdin at all — not running inside Claude Code statusLine
                if json_output:
                    print(json.dumps({
                        "success": False,
                        "error": "No stdin data. Run inside Claude Code statusLine.",
                        "meta": {"model": model_id, "display_name": display_name,
                                 "bypass": bypass},
                    }))
                else:
                    print(f"⚠ Run inside Claude Code statusLine for rate-limit data | {model}")

    except Exception as e:
        reset_time = calculate_reset_time(reset_hour=reset_hour).replace(" ", "")
        _, display_name = get_current_model(stdin_data)
        bypass = is_bypass_permissions_active()
        if json_output:
            print(json.dumps({"success": False, "error": str(e)}))
        else:
            print(_render_style(
                chosen_style,
                msgs_pct=None, weekly_pct=None,
                reset_5h=reset_time, reset_7d="",
                model=display_name, lang_body=lang_body, cost_text=cost_text,
                bypass=bypass, cache_age_text=cache_age_text,
                use_color=use_color, theme=chosen_theme,
                warning_threshold=warning_threshold,
                critical_threshold=critical_threshold,
                density=cfg.density, show_weekly=cfg.show_weekly,
                **identity_kwargs, **mode_kwargs, **ip_line_kwargs,
            ))

if __name__ == '__main__':
    main()
