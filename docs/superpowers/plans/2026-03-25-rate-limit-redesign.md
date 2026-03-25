# Rate-Limit Focused Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current status bar with a dual-progress-bar format focused on rate-limit awareness for Max subscribers.

**Architecture:** Extract progress bar rendering and cache logic into focused modules. Both execution paths (stdin statusLine and standalone) produce the same progress bar output; they differ only in how they obtain the model name. The cache layer sits between claude-monitor (slow subprocess) and the display layer, ensuring statusline calls return in <100ms. Stale cache is served immediately while a background process refreshes it.

**Tech Stack:** Python 3.9+, no new dependencies. pytest for tests.

**Spec:** `docs/superpowers/specs/2026-03-25-rate-limit-focused-redesign.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `src/claude_statusbar/progress.py` | Create | Progress bar rendering (pure functions, no I/O) |
| `src/claude_statusbar/cache.py` | Create | Cache read/write with atomic writes + background refresh |
| `src/claude_statusbar/core.py` | Modify | Slim down: orchestration only, import from new modules |
| `src/claude_statusbar/cli.py` | Modify | Add `--no-color` flag |
| `tests/test_progress.py` | Create | Progress bar unit tests |
| `tests/test_cache.py` | Create | Cache mechanism tests |

---

### Task 1: Progress Bar Renderer

**Files:**
- Create: `src/claude_statusbar/progress.py`
- Create: `tests/test_progress.py`

- [ ] **Step 1: Write failing tests for `build_bar()`**

```python
# tests/test_progress.py
from claude_statusbar.progress import build_bar

def test_bar_zero_percent():
    assert build_bar(0, 10) == "░░░░░░░░░░"

def test_bar_fifty_percent():
    assert build_bar(50, 10) == "█████░░░░░"

def test_bar_100_percent():
    assert build_bar(100, 10) == "██████████"

def test_bar_over_100():
    assert build_bar(120, 10) == "██████████"

def test_bar_small_nonzero_rounds_up():
    """1% should show at least 1 filled block."""
    assert build_bar(1, 10) == "█░░░░░░░░░"

def test_bar_25_percent():
    """25% -> int(2.5 + 0.5) = 3 blocks (always rounds half-up, not banker's)."""
    assert build_bar(25, 10) == "███░░░░░░░"

def test_bar_15_percent():
    """15% -> int(1.5 + 0.5) = 2 blocks."""
    assert build_bar(15, 10) == "██░░░░░░░░"

def test_bar_boundary_values():
    """Test at various boundaries to confirm half-up rounding."""
    assert build_bar(5, 10) == "█░░░░░░░░░"   # int(0.5+0.5)=1
    assert build_bar(45, 10) == "█████░░░░░"   # int(4.5+0.5)=5
    assert build_bar(99, 10) == "██████████"    # int(9.9+0.5)=10
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/leo/github.com/claude-statusbar-monitor && python -m pytest tests/test_progress.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement `build_bar()`**

```python
# src/claude_statusbar/progress.py
"""Progress bar rendering for the status bar. Pure functions, no I/O."""

from typing import Optional

FILL = "█"
EMPTY = "░"


def build_bar(percent: float, width: int = 10) -> str:
    """Render a progress bar string.

    Uses half-up rounding (not Python's banker's rounding) to avoid
    surprising behavior at .5 boundaries.

    Args:
        percent: 0-100+ (clamped to 0-100 for display).
        width: number of characters in the bar.

    Returns:
        String of width characters using FILL and EMPTY.
    """
    clamped = max(0.0, min(percent, 100.0))
    filled = int(clamped / 100 * width + 0.5)  # half-up rounding
    # At least 1 filled block when percent > 0
    if percent > 0 and filled == 0:
        filled = 1
    return FILL * filled + EMPTY * (width - filled)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_progress.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/claude_statusbar/progress.py tests/test_progress.py
git commit -m "feat: add progress bar renderer with tests"
```

---

### Task 2: Color Logic

**Files:**
- Modify: `src/claude_statusbar/progress.py`
- Modify: `tests/test_progress.py`

- [ ] **Step 1: Write failing tests for `color_for_percent()` and `colorize()`**

```python
# append to tests/test_progress.py
from claude_statusbar.progress import color_for_percent, colorize, GREEN, YELLOW, RED, RESET

def test_color_safe():
    assert color_for_percent(20) == GREEN

def test_color_warning():
    assert color_for_percent(50) == YELLOW

def test_color_critical():
    assert color_for_percent(80) == RED

def test_color_boundary_30():
    assert color_for_percent(30) == YELLOW

def test_color_boundary_70():
    assert color_for_percent(70) == RED

def test_colorize():
    result = colorize("hello", RED)
    assert result == f"{RED}hello{RESET}"

def test_colorize_no_color():
    result = colorize("hello", RED, use_color=False)
    assert result == "hello"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_progress.py -v`
Expected: FAIL — functions not found

- [ ] **Step 3: Implement color functions**

```python
# add to src/claude_statusbar/progress.py

GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"


def color_for_percent(percent: float) -> str:
    """Return ANSI color code based on threshold."""
    if percent >= 70:
        return RED
    if percent >= 30:
        return YELLOW
    return GREEN


def colorize(text: str, color: str, use_color: bool = True) -> str:
    """Wrap text in ANSI color codes. No-op when use_color is False."""
    if not use_color:
        return text
    return f"{color}{text}{RESET}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_progress.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/claude_statusbar/progress.py tests/test_progress.py
git commit -m "feat: add color threshold logic"
```

---

### Task 3: `format_status_line()` — Assemble the Full Output

**Files:**
- Modify: `src/claude_statusbar/progress.py`
- Modify: `tests/test_progress.py`

- [ ] **Step 1: Write failing tests for `format_status_line()`**

```python
# append to tests/test_progress.py
from claude_statusbar.progress import format_status_line

def test_format_status_line_basic():
    line = format_status_line(
        msgs_pct=82, tkns_pct=42,
        reset_time="2h51m", model="Opus 4.6",
        use_color=False,
    )
    assert "[████████░░] msgs 82%" in line
    assert "[████░░░░░░] tkns 42%" in line
    assert "2h51m" in line
    assert "Opus 4.6" in line

def test_format_status_line_over_100():
    line = format_status_line(
        msgs_pct=105, tkns_pct=100,
        reset_time="0h03m", model="Opus 4.6",
        use_color=False,
    )
    assert "msgs 100%+" in line
    assert "[██████████]" in line

def test_format_status_line_no_data():
    line = format_status_line(
        msgs_pct=None, tkns_pct=None,
        reset_time="--", model="unknown",
        use_color=False,
    )
    assert "msgs --%" in line
    assert "[░░░░░░░░░░]" in line

def test_format_status_line_bypass():
    line = format_status_line(
        msgs_pct=50, tkns_pct=20,
        reset_time="3h00m", model="Sonnet",
        bypass=True, use_color=False,
    )
    assert "BYPASS" in line

def test_format_status_line_with_color():
    """Verify ANSI codes are present when use_color=True."""
    line = format_status_line(
        msgs_pct=80, tkns_pct=20,
        reset_time="1h00m", model="Opus",
        use_color=True,
    )
    assert "\033[" in line  # ANSI escape present
    assert "\033[0m" in line  # RESET present
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_progress.py::test_format_status_line_basic -v`
Expected: FAIL

- [ ] **Step 3: Implement `format_status_line()`**

Note: bars and labels are colorized separately to avoid ANSI RESET nesting issues.

```python
# add to src/claude_statusbar/progress.py

def format_status_line(
    msgs_pct: Optional[float],
    tkns_pct: Optional[float],
    reset_time: str,
    model: str,
    bypass: bool = False,
    use_color: bool = True,
) -> str:
    """Build the complete status bar string.

    Each progress bar is colored independently. Surrounding text (labels,
    separators, timer, model) uses the highest severity color.
    """
    # Overall color for text/separators = max severity
    overall_color = color_for_percent(max(msgs_pct or 0, tkns_pct or 0))

    # Messages bar
    if msgs_pct is not None:
        m_bar = build_bar(msgs_pct)
        m_label = "100%+" if msgs_pct > 100 else f"{msgs_pct:.0f}%"
        m_color = color_for_percent(msgs_pct)
    else:
        m_bar = EMPTY * 10
        m_label = "--%"
        m_color = GREEN

    # Tokens bar
    if tkns_pct is not None:
        t_bar = build_bar(tkns_pct)
        t_label = "100%+" if tkns_pct > 100 else f"{tkns_pct:.0f}%"
        t_color = color_for_percent(tkns_pct)
    else:
        t_bar = EMPTY * 10
        t_label = "--%"
        t_color = GREEN

    # Build parts: bar colored by its own severity, label by overall
    msgs_part = (
        f"{colorize('[' + m_bar + ']', m_color, use_color)}"
        f" {colorize('msgs ' + m_label, overall_color, use_color)}"
    )
    tkns_part = (
        f"{colorize('[' + t_bar + ']', t_color, use_color)}"
        f" {colorize('tkns ' + t_label, overall_color, use_color)}"
    )
    time_part = colorize(f"⏰{reset_time}", overall_color, use_color)
    model_part = colorize(model, overall_color, use_color)

    parts = [msgs_part, tkns_part, time_part, model_part]
    if bypass:
        parts.append(colorize("⚠️BYPASS", RED, use_color))

    separator = colorize(" | ", overall_color, use_color)
    return separator.join(parts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_progress.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/claude_statusbar/progress.py tests/test_progress.py
git commit -m "feat: add format_status_line assembler"
```

---

### Task 4: Cache Module

**Files:**
- Create: `src/claude_statusbar/cache.py`
- Create: `tests/test_cache.py`

- [ ] **Step 1: Write failing tests for cache read/write**

```python
# tests/test_cache.py
import json
import time
from pathlib import Path
from claude_statusbar.cache import (
    read_cache, read_cache_stale, write_cache, CACHE_MAX_AGE_S,
)

def test_write_and_read(tmp_path):
    cache_file = tmp_path / "cache.json"
    data = {"messages_count": 100, "message_limit": 250}
    write_cache(data, cache_file)
    result = read_cache(cache_file)
    assert result is not None
    assert result["messages_count"] == 100

def test_read_missing_file(tmp_path):
    cache_file = tmp_path / "nonexistent.json"
    assert read_cache(cache_file) is None

def test_read_stale_cache_returns_none(tmp_path):
    cache_file = tmp_path / "cache.json"
    data = {"messages_count": 50}
    write_cache(data, cache_file)
    # Manually backdate the timestamp
    raw = json.loads(cache_file.read_text())
    raw["_cache_time"] = time.time() - CACHE_MAX_AGE_S - 10
    cache_file.write_text(json.dumps(raw))
    assert read_cache(cache_file) is None

def test_read_stale_cache_with_stale_ok(tmp_path):
    """read_cache_stale returns data even if expired."""
    cache_file = tmp_path / "cache.json"
    write_cache({"messages_count": 50}, cache_file)
    raw = json.loads(cache_file.read_text())
    raw["_cache_time"] = time.time() - CACHE_MAX_AGE_S - 10
    cache_file.write_text(json.dumps(raw))
    result = read_cache_stale(cache_file)
    assert result is not None
    assert result["messages_count"] == 50

def test_write_is_atomic(tmp_path):
    """Cache file should never be half-written."""
    cache_file = tmp_path / "cache.json"
    write_cache({"a": 1}, cache_file)
    result = json.loads(cache_file.read_text())
    assert "_cache_time" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_cache.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement cache module**

```python
# src/claude_statusbar/cache.py
"""Cache layer for claude-monitor data.

Atomic writes, age-based invalidation, and stale-read support for
serving old data while a background refresh runs.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional

CACHE_MAX_AGE_S = 30
CACHE_DIR = Path.home() / ".cache" / "claude-statusbar"
CACHE_FILE = CACHE_DIR / "cache.json"


def read_cache(path: Path = CACHE_FILE) -> Optional[Dict[str, Any]]:
    """Read cache if fresh (<CACHE_MAX_AGE_S seconds old).

    Returns None if missing, corrupt, or stale.
    """
    try:
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        cache_time = raw.get("_cache_time", 0)
        if time.time() - cache_time > CACHE_MAX_AGE_S:
            return None
        return raw
    except (json.JSONDecodeError, OSError):
        return None


def read_cache_stale(path: Path = CACHE_FILE) -> Optional[Dict[str, Any]]:
    """Read cache regardless of age. Returns None only if missing/corrupt."""
    try:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def write_cache(data: Dict[str, Any], path: Path = CACHE_FILE) -> None:
    """Atomically write data to cache file.

    Writes to a temp file first, then renames to prevent partial reads.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {**data, "_cache_time": time.time()}
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.rename(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def refresh_cache_background() -> None:
    """Spawn a detached subprocess to refresh the cache.

    The subprocess runs `python -m claude_statusbar.cache_refresh` which
    calls claude-monitor and writes the result to cache. This way the
    main process can return immediately with stale data.
    """
    try:
        subprocess.Popen(
            [sys.executable, "-m", "claude_statusbar.cache_refresh"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        pass  # Best-effort; if it fails, next call will do a sync refresh
```

- [ ] **Step 4: Create the background refresh entry point**

```python
# src/claude_statusbar/cache_refresh.py
"""Background cache refresh entry point.

Called by cache.refresh_cache_background() as a detached subprocess.
Fetches fresh data from claude-monitor and writes to cache.
"""

from .core import try_original_analysis, direct_data_analysis, calculate_reset_time
from .cache import write_cache


def main():
    usage_data = try_original_analysis()
    if not usage_data:
        usage_data = direct_data_analysis()
    if usage_data:
        # Include reset_time in cache so main process doesn't need subprocess
        reset_time = calculate_reset_time()
        usage_data["_reset_time"] = reset_time
        write_cache(usage_data)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_cache.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add src/claude_statusbar/cache.py src/claude_statusbar/cache_refresh.py tests/test_cache.py
git commit -m "feat: add cache module with atomic writes and background refresh"
```

---

### Task 5: Integrate — Rewrite `core.py` Main Path

**Files:**
- Modify: `src/claude_statusbar/core.py`

Both stdin and standalone paths now:
1. Read cache (or serve stale + background refresh if expired)
2. Call `format_status_line()` with the same progress bar format
3. Model comes from stdin when available, else from usage data

- [ ] **Step 1: Add `fetch_usage_data()` that wraps cache + claude-monitor**

Add to `core.py` after the existing data-fetching functions.

Key design decisions from review:
- Cache stores **raw** data without plan overrides (plan may change between calls)
- Stale cache is served immediately while background refresh runs
- `reset_time` is cached to avoid redundant subprocess calls

```python
from .cache import read_cache, read_cache_stale, write_cache, refresh_cache_background
from .progress import format_status_line

def fetch_usage_data(plan: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Get usage data, using cache when fresh.

    1. Fresh cache (<30s) → return immediately
    2. Stale cache → return stale data, spawn background refresh
    3. No cache → synchronous fetch (cold start)

    Plan overrides are applied AFTER cache read (never stored in cache).
    """
    # Try fresh cache
    cached = read_cache()
    if cached is not None:
        return apply_plan_override(cached, plan)

    # Try stale cache + background refresh
    stale = read_cache_stale()
    if stale is not None:
        refresh_cache_background()
        return apply_plan_override(stale, plan)

    # Cold start — synchronous fetch
    usage_data = try_original_analysis()
    if not usage_data:
        usage_data = direct_data_analysis()
    if usage_data:
        # Cache reset_time to avoid subprocess on next call
        reset_time = calculate_reset_time()
        usage_data["_reset_time"] = reset_time
        write_cache(usage_data)
        return apply_plan_override(usage_data, plan)

    return None
```

- [ ] **Step 2: Rewrite `main()` to use unified format**

Replace the display logic in `main()`. Both paths call `format_status_line()`:

```python
def main(json_output: bool = False, plan: Optional[str] = None,
         reset_hour: Optional[int] = None, use_color: bool = True):
    """Main function"""
    stdin_data = parse_stdin_data()

    try:
        if not json_output:
            check_for_updates()

        # Fetch usage data (cache-aware)
        usage_data = fetch_usage_data(plan=plan)

        # Model: prefer stdin, fallback to usage_data
        model_id, display_name = get_current_model(stdin_data)
        if model_id == 'unknown' and usage_data:
            data_models = usage_data.get('models', [])
            if data_models:
                model_id = data_models[0]
                display_name = model_id

        # Calculate percentages
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

        # Reset time: use cached value if available, else compute
        if usage_data and usage_data.get('_reset_time'):
            reset_time = usage_data['_reset_time']
        else:
            reset_time = calculate_reset_time(reset_hour=reset_hour)
        reset_time = reset_time.replace(" ", "")

        bypass = is_bypass_permissions_active()

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
```

- [ ] **Step 3: Remove old display functions**

Delete these functions from `core.py` (replaced by `progress.py`):
- `format_statusbar_from_stdin()`
- `generate_statusbar_text()`
- `build_stdin_json_output()`
- `format_number()`
- `class Colors`

- [ ] **Step 4: Fix remaining hardcoded limits**

In `direct_data_analysis()` (~line 386): change `'message_limit': 755` to `'message_limit': 250`.

In `main()` fallback block (~line 893): change `"message_limit": PLAN_PRESETS.get("pro", {}).get("message_limit", 755)` to use `250` as the hardcoded default.

- [ ] **Step 5: Run full test suite and manual test**

Run: `python -m pytest tests/ -v`

Manual tests:
```bash
# Standalone (cold start — will be slow first time)
cs

# Second call within 30s (should be fast from cache)
cs

# Simulated stdin (model from stdin, data from cache)
echo '{"model":{"id":"claude-opus-4-6","display_name":"Opus 4.6"}}' | cs

# JSON
cs --json-output | python -m json.tool
```

Expected standalone output:
```
[████████░░] msgs 82% | [████░░░░░░] tkns 42% | ⏰2h51m | Opus 4.6
```

- [ ] **Step 6: Commit**

```bash
git add src/claude_statusbar/core.py
git commit -m "feat: rewrite display to use dual progress bars with cache"
```

---

### Task 6: Add `--no-color` Flag

**Files:**
- Modify: `src/claude_statusbar/cli.py`

- [ ] **Step 1: Add `--no-color` argument to CLI**

```python
# In cli.py, add after the --reset-hour argument:
parser.add_argument(
    "--no-color",
    action="store_true",
    help="Disable ANSI color codes in output",
)
```

- [ ] **Step 2: Pass `use_color` to `main()`**

```python
# In cli.py, update the main call:
# Also respect the NO_COLOR env convention (https://no-color.org/)
use_color = not (args.no_color or env_bool("NO_COLOR"))
statusbar_main(json_output=json_output, plan=plan, reset_hour=reset_hour, use_color=use_color)
```

- [ ] **Step 3: Manual test**

```bash
cs --no-color
# Should show: [████████░░] msgs 82% | ... without ANSI codes

cs | cat -v
# Should show escape codes: ^[[32m...

cs --no-color | cat -v
# Should show no escape codes
```

- [ ] **Step 4: Commit**

```bash
git add src/claude_statusbar/cli.py
git commit -m "feat: add --no-color flag and NO_COLOR env support"
```

---

### Task 7: Clean Up and Version Bump

**Files:**
- Modify: `pyproject.toml` — bump version to 2.0.0

- [ ] **Step 1: Bump version**

In `pyproject.toml`, change:
```toml
version = "2.0.0"
```

This is a major version bump because the output format is a breaking change.

- [ ] **Step 2: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: all PASS

- [ ] **Step 3: Full integration test**

```bash
pip install -e .
cs                    # progress bars
cs --json-output      # JSON with all fields
cs --no-color         # no ANSI
cs --plan max5        # override limits
CLAUDE_SKIP_PERMISSIONS=1 cs  # bypass indicator
```

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "feat: v2.0.0 — rate-limit focused status bar redesign

Dual progress bars (messages + tokens) replace the old emoji format.
Cache layer for fast statusline response (<100ms).
Background refresh for stale cache. --no-color support."
```
