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

def try_original_analysis() -> Optional[Dict[str, Any]]:
    """Try to use the installed claude-monitor package"""
    # Local imports — these are heavy stdlib modules that we only need on
    # the slow analysis path (most renders hit the cached fast path).
    import shutil
    import subprocess
    try:
        # Check if claude-monitor is installed
        claude_monitor_cmd = shutil.which('claude-monitor')
        if not claude_monitor_cmd:
            # Try other command aliases
            for cmd in ['cmonitor', 'ccmonitor', 'ccm']:
                claude_monitor_cmd = shutil.which(cmd)
                if claude_monitor_cmd:
                    break

        if not claude_monitor_cmd:
            _get_logger().info("claude-monitor not found. Install with: uv tool install claude-monitor")
            return None
        
        # Find the Python interpreter used by claude-monitor
        # Check common installation paths
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
            # Try to extract from the shebang of claude-monitor script
            try:
                with open(claude_monitor_cmd, 'r') as f:
                    first_line = f.readline()
                    if first_line.startswith('#!'):
                        claude_python = first_line[2:].strip()
            except:
                pass
        
        if not claude_python:
            _get_logger().info("Could not find claude-monitor Python interpreter")
            return None
        
        # Use subprocess to run analysis with the correct Python
        code = """
import json
import sys
try:
    # Version compatibility check
    import claude_monitor
    version = getattr(claude_monitor, '__version__', 'unknown')
    
    from claude_monitor.data.analysis import analyze_usage
    from claude_monitor.core.plans import get_token_limit
    
    result = analyze_usage(hours_back=192, quick_start=False)
    blocks = result.get('blocks', [])
    
    if not blocks:
        print(json.dumps(None))
        sys.exit(0)
    
    # Get active sessions
    active_blocks = [b for b in blocks if b.get('isActive', False)]
    if not active_blocks:
        print(json.dumps(None))
        sys.exit(0)
    
    current_block = active_blocks[0]
    
    # Get P90 limit with compatibility handling
    try:
        token_limit = get_token_limit('custom', blocks)
    except TypeError:
        # Try old API signature
        try:
            token_limit = get_token_limit('custom')
        except:
            token_limit = 113505
    except:
        token_limit = 113505
    
    # Calculate dynamic cost limit using P90 method similar to claude-monitor
    try:
        # Get all historical costs from blocks for P90 calculation
        all_costs = []
        for block in blocks:
            cost = block.get('costUSD', 0)
            if cost > 0:
                all_costs.append(cost)
        
        # Also collect message counts for P90 calculation
        all_messages = []
        for block in blocks:
            msg_count = block.get('sentMessagesCount', len(block.get('entries', [])))
            if msg_count > 0:
                all_messages.append(msg_count)
        
        if len(all_costs) >= 5:
            # Use P90 calculation similar to claude-monitor
            all_costs.sort()
            all_messages.sort()
            p90_index = int(len(all_costs) * 0.9)
            p90_cost = all_costs[min(p90_index, len(all_costs) - 1)]
            # Calculate message limit using P90 method
            if all_messages:
                p90_msg_index = int(len(all_messages) * 0.9)
                p90_messages = all_messages[min(p90_msg_index, len(all_messages) - 1)]
                message_limit = max(int(p90_messages * 1.2), 100)  # Similar to cost calculation
            else:
                message_limit = 250  # Default based on your example
            
            # Apply similar logic to claude-monitor (seems to use a different multiplier)
            cost_limit = max(p90_cost * 1.004, 50.0)  # Adjusted to match observed behavior
        else:
            # Fallback to static limit
            from claude_monitor.core.plans import get_cost_limit
            cost_limit = get_cost_limit('custom')
            message_limit = 250  # Default
    except:
        cost_limit = 90.26  # fallback
    
    # Handle different field name conventions for compatibility
    total_tokens = (current_block.get('totalTokens', 0) or 
                   current_block.get('total_tokens', 0) or 0)
    cost_usd = (current_block.get('costUSD', 0.0) or 
               current_block.get('cost_usd', 0.0) or 
               current_block.get('cost', 0.0) or 0.0)
    entries = current_block.get('entries', []) or []
    messages_count = current_block.get('sentMessagesCount', len(entries))
    is_active = current_block.get('isActive', current_block.get('is_active', False))
    
    # Collect models used in current block
    models = current_block.get('models', [])

    # 7-day totals across ALL non-gap blocks
    from datetime import datetime, timedelta, timezone
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    weekly_tokens = 0
    weekly_msgs = 0
    weekly_cost = 0.0
    for b in blocks:
        if b.get('isGap', False):
            continue
        start = b.get('startTime', '')
        if isinstance(start, str) and start:
            if start.endswith('Z'):
                start = start[:-1] + '+00:00'
            try:
                bt = datetime.fromisoformat(start)
                if bt >= week_ago:
                    weekly_tokens += b.get('totalTokens', 0) or 0
                    weekly_msgs += b.get('sentMessagesCount', 0) or 0
                    weekly_cost += b.get('costUSD', 0.0) or 0.0
            except:
                pass

    output = {
        'total_tokens': total_tokens,
        'token_limit': token_limit,
        'cost_usd': cost_usd,
        'cost_limit': cost_limit,
        'messages_count': messages_count,
        'message_limit': message_limit,
        'entries_count': len(entries),
        'is_active': is_active,
        'plan_type': 'CUSTOM',
        'source': 'original',
        'models': models,
        'weekly_tokens': weekly_tokens,
        'weekly_msgs': weekly_msgs,
        'weekly_cost': weekly_cost,
    }
    print(json.dumps(output))
except Exception as e:
    print(json.dumps(None))
    sys.exit(1)
"""
        
        # Run the code with the claude-monitor Python interpreter
        result = subprocess.run(
            [claude_python, '-c', code],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0 and result.stdout:
            data = json.loads(result.stdout.strip())
            if data:
                return data
        
        return None
        
    except Exception as e:
        _get_logger().error(f"Original analysis failed: {e}")
        return None

def direct_data_analysis() -> Optional[Dict[str, Any]]:
    """Directly analyze Claude data files, completely independent implementation"""
    try:
        def build_candidate_paths() -> List[Path]:
            """Collect plausible data directories in priority order."""
            paths: List[Path] = []
            
            # Respect Claude Code env override
            env_dir = os.environ.get("CLAUDE_CONFIG_DIR")
            if env_dir:
                env_path = Path(env_dir).expanduser()
                if env_path.name == ".claude":
                    paths.append(env_path)
                    paths.append(env_path / "projects")
                else:
                    paths.append(env_path / ".claude")
                    paths.append(env_path / ".claude" / "projects")
            
            # Running from inside .claude
            cwd = Path.cwd()
            if cwd.name == ".claude":
                paths.append(cwd)
                paths.append(cwd / "projects")
            
            # Standard locations
            paths.extend([
                Path.home() / '.claude' / 'projects',
                Path.home() / '.config' / 'claude' / 'projects',
                Path.home() / '.claude',
            ])
            
            # Deduplicate while preserving order
            seen = set()
            unique_paths: List[Path] = []
            for p in paths:
                if p not in seen:
                    unique_paths.append(p)
                    seen.add(p)
            return unique_paths

        data_path = None
        for path in build_candidate_paths():
            if path.exists() and path.is_dir():
                data_path = path
                break
        
        if not data_path:
            return None
        
        # Collect data from the last 5 hours (simulate session window)
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=5)
        current_session_data = []
        
        # Collect historical data for P90 calculation
        history_cutoff = datetime.now(timezone.utc) - timedelta(days=8)
        all_sessions = []
        current_session_tokens = 0
        current_session_cost = 0.0
        last_time = None
        
        # Read JSONL files, but skip ones whose mtime is older than the
        # history window (with 1-day slack for clock skew). Heavy users have
        # thousands of session files; without this prefilter we re-read every
        # one of them on every fallback render.
        history_cutoff_ts = (history_cutoff - timedelta(days=1)).timestamp()

        def _recent_files():
            for f in data_path.rglob("*.jsonl"):
                try:
                    mtime = f.stat().st_mtime
                except OSError:
                    continue
                if mtime < history_cutoff_ts:
                    continue
                yield f, mtime

        for jsonl_file, _ in sorted(_recent_files(), key=lambda pair: pair[1]):
            try:
                with open(jsonl_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        
                        try:
                            data = json.loads(line)
                            
                            # Parse timestamp
                            timestamp_str = data.get('timestamp', '')
                            if not timestamp_str:
                                continue
                            
                            if timestamp_str.endswith('Z'):
                                timestamp_str = timestamp_str[:-1] + '+00:00'
                            
                            timestamp = datetime.fromisoformat(timestamp_str)
                            
                            # Extract usage data
                            usage = data.get('usage', {})
                            if not usage and 'message' in data and isinstance(data['message'], dict):
                                usage = data['message'].get('usage', {})
                            
                            if not usage:
                                continue
                            
                            # Calculate tokens
                            input_tokens = usage.get('input_tokens', 0)
                            output_tokens = usage.get('output_tokens', 0)
                            cache_creation = usage.get('cache_creation_input_tokens', 0)
                            cache_read = usage.get('cache_read_input_tokens', 0)
                            
                            total_tokens = input_tokens + output_tokens + cache_creation
                            
                            if total_tokens == 0:
                                continue
                            
                            # Estimate cost (simplified pricing model)
                            # Based on Sonnet 3.5 pricing: input $3/M tokens, output $15/M tokens
                            cost = (input_tokens * 3 + output_tokens * 15 + cache_creation * 3.75) / 1000000
                            
                            entry = {
                                'timestamp': timestamp,
                                'total_tokens': total_tokens,
                                'cost': cost,
                                'input_tokens': input_tokens,
                                'output_tokens': output_tokens,
                                'cache_creation': cache_creation,
                                'cache_read': cache_read
                            }
                            
                            # Current 5-hour session data
                            if timestamp >= cutoff_time:
                                current_session_data.append(entry)
                            
                            # Historical session grouping (for P90 calculation)
                            if timestamp >= history_cutoff:
                                if (last_time is None or 
                                    (timestamp - last_time).total_seconds() > 5 * 3600):
                                    # Save previous session
                                    if current_session_tokens > 0:
                                        all_sessions.append({
                                            'tokens': current_session_tokens,
                                            'cost': current_session_cost
                                        })
                                    # Start new session
                                    current_session_tokens = total_tokens
                                    current_session_cost = cost
                                else:
                                    # Continue current session
                                    current_session_tokens += total_tokens
                                    current_session_cost += cost
                                
                                last_time = timestamp
                        
                        except (json.JSONDecodeError, ValueError, TypeError):
                            continue
                            
            except Exception:
                continue
        
        # Save last session
        if current_session_tokens > 0:
            all_sessions.append({
                'tokens': current_session_tokens,
                'cost': current_session_cost
            })
        
        if not current_session_data:
            return None
        
        # Calculate current session statistics
        total_tokens = sum(e['total_tokens'] for e in current_session_data)
        total_cost = sum(e['cost'] for e in current_session_data)
        
        # Calculate P90 limit
        if len(all_sessions) >= 5:
            session_tokens = [s['tokens'] for s in all_sessions]
            session_costs = [s['cost'] for s in all_sessions]
            session_tokens.sort()
            session_costs.sort()
            
            p90_index = int(len(session_tokens) * 0.9)
            token_limit = max(session_tokens[min(p90_index, len(session_tokens) - 1)], 19000)
            cost_limit = max(session_costs[min(p90_index, len(session_costs) - 1)] * 1.2, 18.0)
        else:
            # Default limits
            if total_tokens > 100000:
                token_limit, cost_limit = 220000, 140.0
            elif total_tokens > 50000:
                token_limit, cost_limit = 88000, 35.0
            else:
                token_limit, cost_limit = 19000, 18.0
        
        return {
            'total_tokens': total_tokens,
            'token_limit': int(token_limit),
            'cost_usd': total_cost,
            'cost_limit': cost_limit,
            'messages_count': len(current_session_data),  # Each entry is a message
            'message_limit': 250,  # Default fallback
            'entries_count': len(current_session_data),
            'is_active': True,
            'plan_type': 'CUSTOM' if len(all_sessions) >= 5 else 'AUTO',
            'source': 'direct'
        }
        
    except Exception as e:
        _get_logger().error(f"Direct analysis failed: {e}")
        return None

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

        # Only cache stdin when it contains rate_limits (avoid overwriting with empty data).
        # Atomic write — Ctrl+C must not corrupt the cache.
        if data.get('rate_limits', {}).get('five_hour'):
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

        # Rate limits (Claude.ai Pro/Max only)
        # Coerce percentages to int and clamp to [0, ∞):
        # - Anthropic occasionally returns floats like 56.00000000000001
        # - Reject NaN/inf so they never reach the renderer
        # - Clamp negatives to 0 (defensive — should never happen in practice)
        # - Don't cap at 100; values >100% are valid for over-quota indicators
        import math
        import time as _time
        def _pct(v):
            try:
                f = float(v)
            except (TypeError, ValueError):
                return 0
            if math.isnan(f) or math.isinf(f):
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
        # Try the same method as try_original_analysis to get session data
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
    
    # Fallback: estimate reset time (assume session started within the last 5 hours)
    now = datetime.now()
    # Assume reset time is 2 PM (consistent with original project display)
    today_2pm = now.replace(hour=14, minute=0, second=0, microsecond=0)
    tomorrow_2pm = today_2pm + timedelta(days=1)
    
    # Choose next 2 PM
    next_reset = tomorrow_2pm if now >= today_2pm else today_2pm
    diff = next_reset - now
    
    total_minutes = int(diff.total_seconds() / 60)
    hours = total_minutes // 60
    mins = total_minutes % 60
    
    return f"{hours}h {mins:02d}m"

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

        from .updater import check_and_upgrade
        success, message = check_and_upgrade()

        if success:
            print(f"🔄 {message}", file=sys.stderr)

    except Exception:
        # Silently fail - don't interrupt main functionality
        pass


def _time_now() -> float:
    """Indirection so tests can monkeypatch."""
    import time as _t
    return _t.time()

def build_json_output(usage_data: Dict[str, Any], reset_time: str, model: str, display_name: str) -> Dict[str, Any]:
    """Create machine-readable payload."""
    return {
        "success": True,
        "usage": {
            "total_tokens": usage_data.get("total_tokens", 0),
            "token_limit": usage_data.get("token_limit", 0),
            "cost_usd": usage_data.get("cost_usd", 0.0),
            "cost_limit": usage_data.get("cost_limit", 0.0),
            "messages_count": usage_data.get("messages_count", 0),
            "message_limit": usage_data.get("message_limit", 0),
            "plan_type": usage_data.get("plan_type"),
            "source": usage_data.get("source", "unknown"),
        },
        "meta": {
            "model": model,
            "display_name": display_name,
            "reset_time": reset_time,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }


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
         warning_threshold: float = 30.0, critical_threshold: float = 70.0,
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
        )
        # git ahead/behind reuses the same cached `git status --branch` the
        # dirty refresh just triggered — only meaningful on the identity line.
        if cfg.show_ahead_behind and info.toplevel:
            from .identity import read_ahead_behind
            ahead, behind = read_ahead_behind(info.toplevel)
            identity_kwargs["identity_ahead"] = ahead
            identity_kwargs["identity_behind"] = behind

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

        if has_official:
            # ✅ Official data from Anthropic API headers (Claude Code ≥ v2.1.80)
            msgs_pct = stdin_data.get('rate_limit_pct')
            weekly_pct = stdin_data.get('rate_limit_7d_pct')

            resets_at = stdin_data.get('rate_limit_resets_at')
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

            resets_at_7d = stdin_data.get('rate_limit_7d_resets_at')
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
                ctx_size = stdin_data.get('context_window_size', 0)
                raw_pct = stdin_data.get('context_used_pct', 0)
                # ctx_pct: Optional[float] for the renderer.
                # ctx_size > 0 is the discriminator (not raw_pct, which is falsy at 0%).
                ctx_pct = float(raw_pct) if ctx_size > 0 else None
                if raw_pct and ctx_size:
                    ctx_used = int(ctx_size * raw_pct / 100)
                else:
                    ctx_used = stdin_data.get('total_input_tokens', 0) + stdin_data.get('total_output_tokens', 0)
                if ctx_size > 0:
                    # Strip redundant size suffix like "(1M context)" from display_name
                    import re as _re
                    model = _re.sub(r'\s*\([^)]*context[^)]*\)', '', model)
                    model = f"{model}({format_number(ctx_used)}/{format_number(ctx_size)})"

                countdown = get_countdown_emoji(minutes_to_reset)

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
                    **identity_kwargs,
                    **activity_kwargs,
                ))
        else:
            # No rate_limits yet — could be session start or old Claude Code
            model = display_name if display_name != 'Unknown' else model_id
            version = stdin_data.get('claude_version', '') if stdin_data.get('_has_stdin') else ''

            if stdin_data.get('_has_stdin'):
                # Have stdin but no rate_limits — session just started, show placeholders
                ctx_size = stdin_data.get('context_window_size', 0)
                raw_pct = stdin_data.get('context_used_pct', 0)
                # ctx_pct: Optional[float] for the renderer.
                # ctx_size > 0 is the discriminator (not raw_pct, which is falsy at 0%).
                ctx_pct = float(raw_pct) if ctx_size > 0 else None
                if raw_pct and ctx_size:
                    ctx_used = int(ctx_size * raw_pct / 100)
                else:
                    ctx_used = stdin_data.get('total_input_tokens', 0) + stdin_data.get('total_output_tokens', 0)
                if ctx_size > 0:
                    import re as _re
                    model = _re.sub(r'\s*\([^)]*context[^)]*\)', '', model)
                    model = f"{model}({format_number(ctx_used)}/{format_number(ctx_size)})"

                if json_output:
                    print(json.dumps({
                        "success": True, "source": "waiting",
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
                        **identity_kwargs,
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
                **identity_kwargs,
            ))

if __name__ == '__main__':
    main()
