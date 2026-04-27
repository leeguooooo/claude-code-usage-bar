#!/usr/bin/env python3
"""
Claude Code Status Bar Monitor - Final Fixed Version
Resolves dependency issues, ensuring operation in any environment
"""

import json
import re
import sys
import logging
import os
import subprocess
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .cache import read_cache, read_cache_stale, write_cache, refresh_cache_background
from .progress import format_language_body, format_status_line

# Module-local logger: never call logging.basicConfig() at import-time —
# that would clobber the root logger config of any program that imports
# claude_statusbar (cli + lib + tests). Default to ERROR-level + null
# handler so we stay quiet unless the host explicitly enables our logs.
logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)
logger.addHandler(logging.NullHandler())

def try_original_analysis() -> Optional[Dict[str, Any]]:
    """Try to use the installed claude-monitor package"""
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
            logger.info("claude-monitor not found. Install with: uv tool install claude-monitor")
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
            logger.info("Could not find claude-monitor Python interpreter")
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
        logger.error(f"Original analysis failed: {e}")
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
        logger.error(f"Direct analysis failed: {e}")
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

        # Time-based window rollover.
        # Anthropic only pushes fresh rate_limits when the user actually
        # makes a request. Between requests, both the value we receive and
        # any cached value can describe a window that has already expired.
        # Showing "99%" hours after the window reset is misleading.
        #
        # If resets_at is in the past, the old window has clearly rolled
        # over (possibly multiple times). The new window's pct is 0 and
        # its resets_at = old + N × window_length.
        FIVE_HOUR_S  = 5 * 3600
        SEVEN_DAY_S  = 7 * 86400

        def _rollover(pct, resets_at, window_s):
            try:
                resets_at_f = float(resets_at) if resets_at is not None else None
            except (TypeError, ValueError):
                return pct, resets_at
            if resets_at_f is None:
                return pct, resets_at
            now = _time.time()
            if resets_at_f > now:
                return pct, resets_at  # current window still active
            # Advance through however many windows have elapsed.
            elapsed = now - resets_at_f
            windows_passed = int(elapsed // window_s) + 1
            return 0, int(resets_at_f + windows_passed * window_s)
        rl = data.get('rate_limits', {})
        fh = rl.get('five_hour', {})
        if fh:
            p, ra = _rollover(_pct(fh.get('used_percentage', 0)),
                               fh.get('resets_at'), FIVE_HOUR_S)
            result['rate_limit_pct'] = p
            result['rate_limit_resets_at'] = ra
        sd = rl.get('seven_day', {})
        if sd:
            p, ra = _rollover(_pct(sd.get('used_percentage', 0)),
                               sd.get('resets_at'), SEVEN_DAY_S)
            result['rate_limit_7d_pct'] = p
            result['rate_limit_7d_resets_at'] = ra

        # Fallback: load rate_limits from previous session's cached stdin
        if not fh and not sd:
            try:
                cached = json.loads(debug_file.read_text(encoding="utf-8"))
                cached_rl = cached.get('rate_limits', {})
                cached_fh = cached_rl.get('five_hour', {})
                cached_sd = cached_rl.get('seven_day', {})
                if cached_fh:
                    p, ra = _rollover(_pct(cached_fh.get('used_percentage', 0)),
                                       cached_fh.get('resets_at'), FIVE_HOUR_S)
                    result['rate_limit_pct'] = p
                    result['rate_limit_resets_at'] = ra
                if cached_sd:
                    p, ra = _rollover(_pct(cached_sd.get('used_percentage', 0)),
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

def check_for_updates(session_id: str = ''):
    """Check for updates once per new session.

    Disabled by setting env CLAUDE_STATUSBAR_NO_UPDATE=1 or
    passing --no-auto-update on the CLI.
    """
    # Respect opt-out
    env_val = os.environ.get('CLAUDE_STATUSBAR_NO_UPDATE', '').lower()
    if env_val in ('1', 'true', 'yes'):
        return

    try:
        cache_dir = Path.home() / '.cache' / 'claude-statusbar'
        cache_dir.mkdir(parents=True, exist_ok=True)
        last_session_file = cache_dir / 'last_update_session'

        # Only check when session changes
        should_check = True
        if session_id and last_session_file.exists():
            try:
                last_session = last_session_file.read_text().strip()
                if last_session == session_id:
                    should_check = False
            except OSError:
                pass

        if not should_check:
            return

        # Mark this session as checked BEFORE running the (potentially slow)
        # upgrade. If the upgrade hangs, the next render won't re-trigger it
        # and the user gets a working status bar instead of a frozen one.
        if session_id:
            try:
                last_session_file.write_text(session_id)
            except OSError:
                pass

        from .updater import check_and_upgrade
        success, message = check_and_upgrade()

        if success:
            print(f"🔄 {message}", file=sys.stderr)

    except Exception:
        # Silently fail - don't interrupt main functionality
        pass

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


def main(json_output: bool = False,
         reset_hour: Optional[int] = None, use_color: bool = True,
         detail: bool = False, pet_name: Optional[str] = None,
         show_pet: bool = True,
         warning_threshold: float = 30.0, critical_threshold: float = 70.0,
         style_override: Optional[str] = None,
         theme_override: Optional[str] = None):
    """Main function"""
    from .pet import format_pet, get_countdown_emoji
    from .setup import ensure_statusline_configured
    from . import config as _cfg
    from .styles import render as _render_style
    from .themes import get_theme

    from .styles import is_known_style as _is_known_style

    cfg = _cfg.load_config()
    chosen_style = _cfg.resolve_style(style_override, cfg)
    if not _is_known_style(chosen_style):
        # Unknown style → silently fall back to the safe default rather than
        # explode in the statusLine where the user can't see the error.
        chosen_style = "classic"
    chosen_theme = get_theme(_cfg.resolve_theme(theme_override, cfg))

    # Auto-compact: if terminal narrower than threshold, force hairline
    if cfg.auto_compact_width > 0 and chosen_style != "hairline":
        try:
            term_w = os.get_terminal_size().columns
            if term_w < cfg.auto_compact_width:
                chosen_style = "hairline"
        except OSError:
            pass

    # Honor show_pet from config (CLI --hide-pet still overrides)
    if not cfg.show_pet:
        show_pet = False

    stdin_data = parse_stdin_data()
    lang_body = format_language_body(
        str(Path.home() / ".claude" / "language-progress.json"),
    ) if cfg.show_language else ""

    try:
        if not json_output:
            check_for_updates(stdin_data.get('session_id', ''))
            # Silently restore statusLine config if a Claude Code upgrade wiped it
            ensure_statusline_configured()

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
                ctx_pct = stdin_data.get('context_used_pct', 0)
                if ctx_pct and ctx_size:
                    ctx_used = int(ctx_size * ctx_pct / 100)
                else:
                    ctx_used = stdin_data.get('total_input_tokens', 0) + stdin_data.get('total_output_tokens', 0)
                if ctx_size > 0:
                    # Strip redundant size suffix like "(1M context)" from display_name
                    model = re.sub(r'\s*\([^)]*context[^)]*\)', '', model)
                    model = f"{model}({format_number(ctx_used)}/{format_number(ctx_size)})"

                session_id = stdin_data.get('session_id', '')
                current_hour = datetime.now().hour
                pet_text = ""
                if show_pet:
                    pet_pct = msgs_pct if msgs_pct is not None else 0
                    pet_text = format_pet(
                        pet_pct, current_hour, session_id, minutes_to_reset, pet_name,
                        progress_path=str(Path.home() / ".claude" / "language-progress.json"),
                        coach_config_path=str(Path.home() / ".claude" / "language-coach.json"),
                        warning_threshold=warning_threshold,
                        critical_threshold=critical_threshold,
                    )
                countdown = get_countdown_emoji(minutes_to_reset)

                print(_render_style(
                    chosen_style,
                    msgs_pct=msgs_pct, weekly_pct=weekly_pct,
                    reset_5h=reset_time, reset_7d=reset_time_7d,
                    model=model, lang_body=lang_body,
                    pet_body=pet_text, bypass=bypass,
                    use_color=use_color, theme=chosen_theme,
                    warning_threshold=warning_threshold,
                    critical_threshold=critical_threshold,
                    countdown_emoji=countdown,
                    density=cfg.density, show_weekly=cfg.show_weekly,
                ))
        else:
            # No rate_limits yet — could be session start or old Claude Code
            model = display_name if display_name != 'Unknown' else model_id
            version = stdin_data.get('claude_version', '') if stdin_data.get('_has_stdin') else ''

            if stdin_data.get('_has_stdin'):
                # Have stdin but no rate_limits — session just started, show placeholders
                ctx_size = stdin_data.get('context_window_size', 0)
                ctx_pct = stdin_data.get('context_used_pct', 0)
                if ctx_pct and ctx_size:
                    ctx_used = int(ctx_size * ctx_pct / 100)
                else:
                    ctx_used = stdin_data.get('total_input_tokens', 0) + stdin_data.get('total_output_tokens', 0)
                if ctx_size > 0:
                    model = re.sub(r'\s*\([^)]*context[^)]*\)', '', model)
                    model = f"{model}({format_number(ctx_used)}/{format_number(ctx_size)})"

                if json_output:
                    print(json.dumps({
                        "success": True, "source": "waiting",
                        "meta": {"model": model_id, "display_name": display_name,
                                 "claude_version": version, "bypass": bypass},
                    }))
                else:
                    session_id = stdin_data.get('session_id', '')
                    current_hour = datetime.now().hour
                    pet_text = ""
                    if show_pet:
                        pet_text = format_pet(
                            0, current_hour, session_id, None, pet_name,
                            progress_path=str(Path.home() / ".claude" / "language-progress.json"),
                            coach_config_path=str(Path.home() / ".claude" / "language-coach.json"),
                            warning_threshold=warning_threshold,
                            critical_threshold=critical_threshold,
                        )
                    print(_render_style(
                        chosen_style,
                        msgs_pct=None, weekly_pct=None,
                        reset_5h="--", reset_7d="",
                        model=model, lang_body=lang_body,
                        pet_body=pet_text, bypass=bypass,
                        use_color=use_color, theme=chosen_theme,
                        warning_threshold=warning_threshold,
                        critical_threshold=critical_threshold,
                        density=cfg.density, show_weekly=cfg.show_weekly,
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
            current_hour = datetime.now().hour
            pet_text = ""
            if show_pet:
                pet_text = format_pet(
                    0, current_hour, '', None, pet_name,
                    progress_path=str(Path.home() / ".claude" / "language-progress.json"),
                    coach_config_path=str(Path.home() / ".claude" / "language-coach.json"),
                    warning_threshold=warning_threshold,
                    critical_threshold=critical_threshold,
                )
            print(_render_style(
                chosen_style,
                msgs_pct=None, weekly_pct=None,
                reset_5h=reset_time, reset_7d="",
                model=display_name, lang_body=lang_body,
                pet_body=pet_text, bypass=bypass,
                use_color=use_color, theme=chosen_theme,
                warning_threshold=warning_threshold,
                critical_threshold=critical_threshold,
                density=cfg.density, show_weekly=cfg.show_weekly,
            ))

if __name__ == '__main__':
    main()
