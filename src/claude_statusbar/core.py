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

# Suppress log output
logging.basicConfig(level=logging.ERROR)

# ANSI color codes
class Colors:
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    RED = '\033[31m'
    RESET = '\033[0m'

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
        # Check common uv installation paths
        uv_paths = [
            Path.home() / ".local/share/uv/tools/claude-monitor/bin/python",
            Path.home() / ".uv/tools/claude-monitor/bin/python",
        ]
        
        claude_python = None
        for path in uv_paths:
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
    
    # Get P90 limit
    try:
        token_limit = get_token_limit('custom', blocks)
    except:
        token_limit = 113505
    
    output = {
        'total_tokens': current_block.get('totalTokens', 0),
        'token_limit': token_limit,
        'cost_usd': current_block.get('costUSD', 0.0) or 0.0,
        'cost_limit': 118.90,
        'entries_count': len(current_block.get('entries', [])),
        'is_active': current_block.get('isActive', False),
        'plan_type': 'CUSTOM',
        'source': 'original'
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
        # Find Claude data directory
        data_paths = [
            Path.home() / '.claude' / 'projects',
            Path.home() / '.config' / 'claude' / 'projects'
        ]
        
        data_path = None
        for path in data_paths:
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
            'entries_count': len(current_session_data),
            'is_active': True,
            'plan_type': 'CUSTOM' if len(all_sessions) >= 5 else 'AUTO',
            'source': 'direct'
        }
        
    except Exception as e:
        logging.error(f"Direct analysis failed: {e}")
        return None

def calculate_reset_time() -> str:
    """Calculate time until session reset (5-hour rolling window)"""
    try:
        
        # Try the same method as try_original_analysis to get session data
        claude_monitor_cmd = shutil.which('claude-monitor')
        if claude_monitor_cmd:
            # Find Python interpreter
            uv_paths = [
                Path.home() / ".local/share/uv/tools/claude-monitor/bin/python",
                Path.home() / ".uv/tools/claude-monitor/bin/python",
            ]
            
            claude_python = None
            for path in uv_paths:
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

def format_number(num: float) -> str:
    """Format number display"""
    if num >= 1000000:
        return f"{num/1000000:.1f}M"
    elif num >= 1000:
        return f"{num/1000:.1f}k"
    else:
        return f"{num:.0f}"

def generate_statusbar_text(usage_data: Dict[str, Any]) -> str:
    """Generate status bar text"""
    total_tokens = usage_data['total_tokens']
    token_limit = usage_data['token_limit']
    cost_usd = usage_data['cost_usd']
    cost_limit = usage_data['cost_limit']
    plan_type = usage_data['plan_type']
    source = usage_data.get('source', 'unknown')
    
    # Calculate percentage
    token_percentage = (total_tokens / token_limit) * 100 if token_limit > 0 else 0
    cost_percentage = (cost_usd / cost_limit) * 100 if cost_limit > 0 else 0
    max_percentage = max(token_percentage, cost_percentage)
    
    # Choose color and display usage
    if max_percentage >= 90:
        color = Colors.RED
        usage_display = f'Usage:{max_percentage:.0f}%'
    elif max_percentage >= 70:
        color = Colors.RED
        usage_display = f'Usage:{max_percentage:.0f}%'
    elif max_percentage >= 30:
        color = Colors.YELLOW
        usage_display = f'Usage:{max_percentage:.0f}%'
    else:
        color = Colors.GREEN
        usage_display = f'Usage:{max_percentage:.0f}%'
    
    # Reset time
    reset_time = calculate_reset_time()
    
    # Format text
    tokens_text = f"T:{format_number(total_tokens)}/{format_number(token_limit)}"
    cost_text = f"$:{cost_usd:.2f}/{cost_limit:.0f}"
    
    status_text = f"🔋 {tokens_text} | {cost_text} | ⌛️{reset_time} | {usage_display}"
    
    return f"{color}{status_text}{Colors.RESET}"

def main():
    """Main function"""
    try:
        # First try original project analysis
        usage_data = try_original_analysis()
        
        # If failed, use direct analysis
        if not usage_data:
            usage_data = direct_data_analysis()
        
        if not usage_data:
            # Final fallback
            reset_time = calculate_reset_time()
            print(f"🔋 T:0/19k | $:0.00/18 | ⌛️{reset_time} | Usage:0%")
            return
        
        # Generate status bar text
        status_text = generate_statusbar_text(usage_data)
        print(status_text)
        
    except Exception as e:
        # Basic display on error
        reset_time = calculate_reset_time()
        print(f"🔋 T:0/19k | $:0.00/18 | ⌛️{reset_time} | ❌")

if __name__ == '__main__':
    main()