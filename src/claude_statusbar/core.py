#!/usr/bin/env python3
"""
Claude Code Status Bar Monitor - Final Fixed Version
Resolves dependency issues, ensuring operation in any environment
"""

import json
import sys
import logging
import os
import subprocess
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any

from .cache import read_cache, read_cache_stale, write_cache, refresh_cache_background
from .progress import format_status_line

# Suppress log output
logging.basicConfig(level=logging.ERROR)

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
            logging.info("claude-monitor not found. Install with: uv tool install claude-monitor")
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
            logging.info("Could not find claude-monitor Python interpreter")
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
        logging.error(f"Original analysis failed: {e}")
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
        
        # Read all JSONL files
        for jsonl_file in sorted(data_path.rglob("*.jsonl"), key=lambda f: f.stat().st_mtime):
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
        logging.error(f"Direct analysis failed: {e}")
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
        data = json.loads(raw)

        # Model
        model_obj = data.get('model', {})
        if isinstance(model_obj, dict):
            result['model_id'] = model_obj.get('id', '')
            result['display_name'] = model_obj.get('display_name', '')

        # Rate limits (Claude.ai Pro/Max only)
        rl = data.get('rate_limits', {})
        fh = rl.get('five_hour', {})
        if fh:
            result['rate_limit_pct'] = fh.get('used_percentage', 0)
            result['rate_limit_resets_at'] = fh.get('resets_at')
        sd = rl.get('seven_day', {})
        if sd:
            result['rate_limit_7d_pct'] = sd.get('used_percentage', 0)

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

        # Mark that we have valid stdin data
        result['_has_stdin'] = True

    except (json.JSONDecodeError, TypeError, AttributeError):
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
                result = subprocess.run(
                    [claude_python, '-c', code],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout.strip()
    except:
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

PLAN_PRESETS = {
    # Base limits from claude-monitor v3.1.0 (non-doubled)
    "pro":    {"token_limit":  19_000, "cost_limit":  18.0, "message_limit":   250},
    "max5":   {"token_limit":  88_000, "cost_limit":  35.0, "message_limit": 1_000},
    "max20":  {"token_limit": 220_000, "cost_limit": 140.0, "message_limit": 2_000},
    "custom": {"token_limit":  44_000, "cost_limit":  50.0, "message_limit":   250},
    # z.ai subscription estimates
    "zai-lite": {"token_limit": 400_000, "cost_limit": 50.0, "message_limit": 120},
    "zai-pro":  {"token_limit": 2_000_000, "cost_limit": 150.0, "message_limit": 600},
    "zai-max":  {"token_limit": 8_000_000, "cost_limit": 600.0, "message_limit": 2_400},
}

# Activity multiplier — Anthropic sometimes runs 2x promotions
DEFAULT_MULTIPLIER = 1

# Ordered from smallest to largest for auto-detection
PLAN_TIERS = ["pro", "max5", "max20"]

CONFIG_DIR = Path.home() / ".cache" / "claude-statusbar"
CONFIG_FILE = CONFIG_DIR / "config.json"


def load_config() -> Dict[str, Any]:
    """Load saved config (plan + multiplier)."""
    try:
        if CONFIG_FILE.exists():
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def save_config(plan: str, multiplier: int) -> None:
    """Save plan and multiplier to config file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps({"plan": plan, "multiplier": multiplier}),
        encoding="utf-8",
    )


def auto_detect_plan(usage_data: Dict[str, Any]) -> tuple[str, int]:
    """Auto-detect plan tier and activity multiplier from actual usage.

    Walks up tiers at 1x, then tries 2x if usage exceeds all 1x tiers.
    Returns (plan_name, multiplier).
    """
    msgs = usage_data.get('messages_count', 0)
    tokens = usage_data.get('total_tokens', 0)

    for mult in (1, 2):
        for tier in PLAN_TIERS:
            preset = PLAN_PRESETS[tier]
            if (msgs <= preset['message_limit'] * mult and
                    tokens <= preset['token_limit'] * mult):
                return tier, mult

    return PLAN_TIERS[-1], 2

def apply_plan_override(usage_data: Dict[str, Any], plan_name: Optional[str],
                        multiplier: int = 1) -> Dict[str, Any]:
    """Apply plan limits with activity multiplier."""
    if not plan_name:
        return usage_data

    normalized = plan_name.lower().replace("_", "-").replace(".", "-")
    preset = PLAN_PRESETS.get(normalized)

    usage_data = usage_data.copy()
    if preset:
        usage_data['token_limit'] = preset['token_limit'] * multiplier
        usage_data['cost_limit'] = preset['cost_limit'] * multiplier
        usage_data['message_limit'] = preset['message_limit'] * multiplier
    usage_data['plan_type'] = normalized
    usage_data['_multiplier'] = multiplier

    return usage_data

def resolve_plan(usage_data: Optional[Dict[str, Any]], cli_plan: Optional[str]) -> tuple[str, int]:
    """Determine effective plan and multiplier.

    Priority: CLI flag > saved config > auto-detect.
    Returns (plan_name, multiplier).
    """
    if cli_plan:
        normalized = cli_plan.lower().replace("_", "-").replace(".", "-")
        if normalized in PLAN_PRESETS and usage_data:
            # Detect multiplier for the specific plan
            preset = PLAN_PRESETS[normalized]
            msgs = usage_data.get('messages_count', 0)
            tokens = usage_data.get('total_tokens', 0)
            mult = 1
            if msgs > preset['message_limit'] or tokens > preset['token_limit']:
                mult = 2  # usage exceeds 1x, must be 2x active
            save_config(normalized, mult)
            return normalized, mult
        if normalized in PLAN_PRESETS:
            save_config(normalized, 1)
            return normalized, 1
        return normalized, 1

    cfg = load_config()
    saved_plan = cfg.get("plan")
    saved_mult = cfg.get("multiplier", 1)

    if saved_plan and saved_plan in PLAN_PRESETS:
        # Only upgrade if usage EXCEEDS saved plan at saved multiplier
        if usage_data:
            preset = PLAN_PRESETS[saved_plan]
            msgs = usage_data.get('messages_count', 0)
            tokens = usage_data.get('total_tokens', 0)
            eff_msg = preset['message_limit'] * saved_mult
            eff_tkn = preset['token_limit'] * saved_mult
            if msgs > eff_msg or tokens > eff_tkn:
                if saved_mult < 2:
                    # Bump to x2 before upgrading tier
                    save_config(saved_plan, 2)
                    return saved_plan, 2
                else:
                    # Already x2, need higher tier
                    detected_plan, detected_mult = auto_detect_plan(usage_data)
                    save_config(detected_plan, detected_mult)
                    return detected_plan, detected_mult
        return saved_plan, saved_mult

    if usage_data:
        detected_plan, detected_mult = auto_detect_plan(usage_data)
        save_config(detected_plan, detected_mult)
        # First run — show setup hint on stderr (won't affect statusline stdout)
        print(
            "\n"
            "╭─ claude-statusbar setup ────────────────────────╮\n"
            "│ Auto-detected: {:<34}│\n"
            "│                                                 │\n"
            "│ If this is wrong, set your plan once:           │\n"
            "│   cs --plan pro     # Pro $20/mo                │\n"
            "│   cs --plan max5    # Max $100/mo               │\n"
            "│   cs --plan max20   # Max $200/mo               │\n"
            "│                                                 │\n"
            "│ Your choice is saved automatically.             │\n"
            "╰─────────────────────────────────────────────────╯"
            .format(
                f"{detected_plan}(x{detected_mult})" if detected_mult > 1
                else detected_plan
            ),
            file=sys.stderr,
        )
        return detected_plan, detected_mult

    return "custom", 1


def fetch_usage_data(plan: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Get usage data, using cache when fresh.

    1. Fresh cache (<30s) -> return immediately
    2. Stale cache -> return stale data, spawn background refresh
    3. No cache -> synchronous fetch (cold start)

    Plan is resolved via: CLI flag > saved config > auto-detect.
    """
    cached = read_cache()
    if cached is not None:
        effective_plan, mult = resolve_plan(cached, plan)
        return apply_plan_override(cached, effective_plan, mult)

    stale = read_cache_stale()
    if stale is not None:
        refresh_cache_background()
        effective_plan, mult = resolve_plan(stale, plan)
        return apply_plan_override(stale, effective_plan, mult)

    usage_data = try_original_analysis()
    if not usage_data:
        usage_data = direct_data_analysis()
    if usage_data:
        reset_time = calculate_reset_time()
        usage_data["_reset_time"] = reset_time
        write_cache(usage_data)
        effective_plan, mult = resolve_plan(usage_data, plan)
        return apply_plan_override(usage_data, effective_plan, mult)

    return None

def check_for_updates():
    """Check for updates once per day"""
    try:
        from datetime import datetime
        
        # Check if we should run update check
        last_check_file = Path.home() / '.claude-statusbar-last-check'
        now = datetime.now()
        
        should_check = True
        if last_check_file.exists():
            try:
                with open(last_check_file, 'r') as f:
                    last_check_str = f.read().strip()
                    last_check = datetime.fromisoformat(last_check_str)
                    # Check once per day
                    if (now - last_check).days < 1:
                        should_check = False
            except:
                pass
        
        if should_check:
            # Run update check in background
            from .updater import check_and_upgrade
            success, message = check_and_upgrade()
            
            # Update last check time
            with open(last_check_file, 'w') as f:
                f.write(now.isoformat())
            
            # If upgrade was successful, notify user
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


def main(json_output: bool = False, plan: Optional[str] = None,
         reset_hour: Optional[int] = None, use_color: bool = True):
    """Main function"""
    stdin_data = parse_stdin_data()

    try:
        if not json_output:
            check_for_updates()

        usage_data = fetch_usage_data(plan=plan)

        model_id, display_name = get_current_model(stdin_data)
        if model_id == 'unknown' and usage_data:
            data_models = usage_data.get('models', [])
            if data_models:
                model_id = data_models[0]
                display_name = model_id

        if usage_data:
            msg_count = usage_data.get('messages_count', 0)
            msg_limit = usage_data.get('message_limit', 250)
            tkn_total = usage_data.get('total_tokens', 0)
            tkn_limit = usage_data.get('token_limit', 44000)
            msgs_pct = (msg_count / msg_limit * 100) if msg_limit > 0 else None
            tkns_pct = (tkn_total / tkn_limit * 100) if tkn_limit > 0 else None
        else:
            msgs_pct = None
            tkns_pct = None

        if usage_data and usage_data.get('_reset_time'):
            reset_time = usage_data['_reset_time']
        else:
            reset_time = calculate_reset_time(reset_hour=reset_hour)
        reset_time = reset_time.replace(" ", "")

        bypass = is_bypass_permissions_active()
        if usage_data:
            plan_name = (usage_data.get('plan_type', '') or '').lower()
            mult = usage_data.get('_multiplier', 1)
            plan_label = f"{plan_name}(x{mult})" if mult > 1 else plan_name
        else:
            plan_label = ''

        if json_output:
            payload = build_json_output(
                usage_data or {}, reset_time, model_id, display_name
            )
            payload["meta"]["bypass_permissions"] = bypass
            if stdin_data.get('_has_stdin'):
                payload["stdin"] = {
                    "session_cost_usd": stdin_data.get("session_cost_usd", 0),
                    "context_used_pct": stdin_data.get("context_used_pct", 0),
                }
            print(json.dumps(payload))
        else:
            print(format_status_line(
                msgs_pct=msgs_pct,
                tkns_pct=tkns_pct,
                reset_time=reset_time,
                model=display_name if display_name != 'Unknown' else model_id,
                plan=plan_label,
                bypass=bypass,
                use_color=use_color,
            ))

    except Exception as e:
        reset_time = calculate_reset_time(reset_hour=reset_hour).replace(" ", "")
        _, display_name = get_current_model(stdin_data)
        bypass = is_bypass_permissions_active()
        if json_output:
            print(json.dumps({"success": False, "error": str(e)}))
        else:
            print(format_status_line(
                msgs_pct=None, tkns_pct=None,
                reset_time=reset_time, model=display_name,
                bypass=bypass, use_color=use_color,
            ))

if __name__ == '__main__':
    main()
