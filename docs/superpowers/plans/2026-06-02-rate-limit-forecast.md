# Rate-limit Forecast Chip — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in (default-on) on-bar forecast chip that shows `⚠~40m` after a 5h/7d window's `⏰reset` only when that window is projected (at the recent burn rate) to hit 100% before it resets.

**Architecture:** A new pure module `predict.py` keeps a tiny account-global sample history (`~/.cache/claude-statusbar/rate_history.json`) of `(ts, used_pct)`, computes a recent-window burn rate (Δpct/Δt), and returns a raw `~<eta>` chip string when `time_to_limit < time_to_reset` (else `None`). `core.main` lazy-imports it inside a `try/except` guard and plumbs two raw chip strings to the renderer, which colors them like `cache_age_text`. Filled bar / `%` / reset timer are untouched. Fails safe: plateau → no chip; any error → no chip, never blanks the bar.

**Tech Stack:** Python 3.9+ stdlib only (`json`, `time`, `pathlib`). Tests: `pytest` (run with `PYTHONPATH=src`). Reuses `cache.atomic_write_text`.

**Spec:** `docs/superpowers/specs/2026-06-02-rate-limit-forecast-design.md`

---

### Task 1: predict.py — pure math (`format_eta`, `burn_rate`, `time_to_limit`)

**Files:**
- Create: `src/claude_statusbar/predict.py`
- Test: `tests/test_predict.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_predict.py
from claude_statusbar.predict import format_eta, burn_rate, time_to_limit


def test_format_eta_seconds():
    assert format_eta(30) == "~30s"

def test_format_eta_minutes_no_seconds():
    assert format_eta(40 * 60) == "~40m"
    assert format_eta(8 * 60 + 59) == "~8m"   # floor to minutes in the <1h band

def test_format_eta_hours():
    assert format_eta(2 * 3600 + 10 * 60) == "~2h10m"

def test_burn_rate_two_samples():
    # 10% over 100s → 0.1 %/s
    assert abs(burn_rate([(1000.0, 20.0), (1100.0, 30.0)], now=1100.0, lookback_s=300) - 0.1) < 1e-9

def test_burn_rate_excludes_old_samples():
    # only the last two are within lookback=120s of now=1200
    samples = [(0.0, 5.0), (1090.0, 20.0), (1190.0, 26.0)]
    assert abs(burn_rate(samples, now=1200.0, lookback_s=120) - (6.0 / 100.0)) < 1e-9

def test_burn_rate_insufficient_samples_is_none():
    assert burn_rate([(1000.0, 20.0)], now=1000.0, lookback_s=300) is None
    assert burn_rate([], now=1000.0, lookback_s=300) is None

def test_burn_rate_non_increasing_is_none():
    assert burn_rate([(1000.0, 30.0), (1100.0, 30.0)], now=1100.0, lookback_s=300) is None  # plateau
    assert burn_rate([(1000.0, 30.0), (1100.0, 20.0)], now=1100.0, lookback_s=300) is None  # dipped (rolling)

def test_burn_rate_zero_dt_is_none():
    assert burn_rate([(1000.0, 20.0), (1000.0, 30.0)], now=1000.0, lookback_s=300) is None

def test_time_to_limit():
    assert abs(time_to_limit(60.0, 0.1) - 400.0) < 1e-9   # (100-60)/0.1

def test_time_to_limit_none_rate():
    assert time_to_limit(60.0, None) is None
    assert time_to_limit(60.0, 0.0) is None

def test_time_to_limit_already_full():
    assert time_to_limit(100.0, 0.1) is None
```

- [ ] **Step 2: Run — expect FAIL (module missing)**

Run: `PYTHONPATH=src pytest tests/test_predict.py -q`
Expected: collection error / `ModuleNotFoundError: claude_statusbar.predict`

- [ ] **Step 3: Implement the pure math**

```python
# src/claude_statusbar/predict.py
"""Rate-limit burn-rate forecast — pure helpers + a tiny account-global sample
store. Stdlib only; lazy-imported on the render path (kept off the banned
import graph). Everything fails safe: insufficient/odd input → None, never raise.
See docs/superpowers/specs/2026-06-02-rate-limit-forecast-design.md."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List, Optional, Tuple

Sample = Tuple[float, float]  # (unix_ts, used_pct)

# Provisional, tune empirically (sensitivity only, not correctness):
LOOKBACK_S = {"five_hour": 30 * 60, "seven_day": 2 * 3600}
_MAX_SAMPLES = 200          # hard cap per series so the file stays tiny
URGENT_ETA_S = 10 * 60      # ≤ this → "hot" color (decided in the renderer)


def format_eta(seconds: float) -> str:
    """Compact `~30s` / `~40m` / `~2h10m`. Minutes band floors seconds away."""
    s = int(seconds)
    if s < 60:
        return f"~{s}s"
    if s < 3600:
        return f"~{s // 60}m"
    return f"~{s // 3600}h{(s % 3600) // 60:02d}m"


def burn_rate(samples: List[Sample], now: float, lookback_s: float) -> Optional[float]:
    """Recent burn in percent/second over samples within `lookback_s` of `now`.
    None when <2 in-window samples, Δt ≤ 0, or the rate is ≤ 0 (plateau/dip —
    e.g. rolling-window ageing-out: fail safe, show nothing)."""
    recent = [(t, p) for (t, p) in samples if 0 <= now - t <= lookback_s]
    if len(recent) < 2:
        return None
    recent.sort()
    (t0, p0), (t1, p1) = recent[0], recent[-1]
    dt = t1 - t0
    dp = p1 - p0
    if dt <= 0 or dp <= 0:
        return None
    return dp / dt


def time_to_limit(used_pct: float, rate: Optional[float]) -> Optional[float]:
    """Seconds to reach 100% at `rate` (%/s). None if not burning or already full."""
    if rate is None or rate <= 0 or used_pct >= 100:
        return None
    return (100.0 - used_pct) / rate
```

- [ ] **Step 4: Run — expect PASS**

Run: `PYTHONPATH=src pytest tests/test_predict.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/claude_statusbar/predict.py tests/test_predict.py
git commit -m "feat(predict): burn-rate math (format_eta, burn_rate, time_to_limit)"
```

---

### Task 2: predict.py — sample store (load / record / save)

**Files:**
- Modify: `src/claude_statusbar/predict.py`
- Test: `tests/test_predict.py`

- [ ] **Step 1: Write failing tests**

```python
# append to tests/test_predict.py
from claude_statusbar.predict import (
    load_history, save_history, record_sample, _HISTORY_PATH,
)


def test_record_appends_on_pct_change():
    hist = {}
    hist = record_sample(hist, "five_hour", 20.0, now=1000.0)
    hist = record_sample(hist, "five_hour", 30.0, now=1100.0)
    assert hist["five_hour"] == [[1000.0, 20.0], [1100.0, 30.0]]

def test_record_dedups_unchanged_pct():
    hist = record_sample({}, "five_hour", 20.0, now=1000.0)
    hist = record_sample(hist, "five_hour", 20.0, now=1100.0)  # same pct → skip
    assert hist["five_hour"] == [[1000.0, 20.0]]

def test_record_prunes_to_max_samples():
    hist = {}
    for i in range(_MAX_SAMPLES + 50):
        hist = record_sample(hist, "five_hour", float(i), now=float(i))  # each pct differs
    assert len(hist["five_hour"]) == _MAX_SAMPLES
    assert hist["five_hour"][-1] == [float(_MAX_SAMPLES + 49), float(_MAX_SAMPLES + 49)]

def test_load_missing_file_is_empty(tmp_path):
    assert load_history(tmp_path / "nope.json") == {}

def test_load_corrupt_file_is_empty(tmp_path):
    p = tmp_path / "h.json"
    p.write_text("not json{", encoding="utf-8")
    assert load_history(p) == {}

def test_save_then_load_roundtrip(tmp_path):
    p = tmp_path / "h.json"
    hist = {"five_hour": [[1.0, 2.0]], "seven_day": []}
    save_history(hist, p)
    assert load_history(p) == hist
```

Add `from claude_statusbar.predict import _MAX_SAMPLES` to the imports.

- [ ] **Step 2: Run — expect FAIL**

Run: `PYTHONPATH=src pytest tests/test_predict.py -q`
Expected: FAIL (names not defined)

- [ ] **Step 3: Implement the store**

```python
# append to src/claude_statusbar/predict.py
_HISTORY_PATH = Path(os.path.expanduser("~")) / ".cache" / "claude-statusbar" / "rate_history.json"


def load_history(path: Optional[Path] = None) -> dict:
    """Read the global sample store; {} on missing/corrupt/unreadable.
    Resolve the default at CALL time (not a def-time default) so tests can
    monkeypatch `predict._HISTORY_PATH`."""
    path = Path(path) if path is not None else _HISTORY_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def record_sample(history: dict, window: str, pct: float, now: float) -> dict:
    """Append (now, pct) for `window` ONLY when pct changed from the last sample
    (used_pct is a step function), then prune to _MAX_SAMPLES. Returns history
    (mutated in place + returned for chaining). Caller persists via save_history."""
    try:
        pct = float(pct)
    except (TypeError, ValueError):
        return history
    series = history.get(window)
    if not isinstance(series, list):
        series = []
        history[window] = series
    if series and series[-1][1] == pct:
        return history  # dedup unchanged pct
    series.append([float(now), pct])
    if len(series) > _MAX_SAMPLES:
        del series[: len(series) - _MAX_SAMPLES]
    return history


def save_history(history: dict, path: Optional[Path] = None) -> None:
    """Atomic write (tmp + os.replace) — concurrent windows can't corrupt it.
    Default resolved at call time (see load_history) so it's monkeypatchable."""
    path = Path(path) if path is not None else _HISTORY_PATH
    from .cache import atomic_write_text
    try:
        atomic_write_text(path, json.dumps(history))
    except OSError:
        pass
```

- [ ] **Step 4: Run — expect PASS**

Run: `PYTHONPATH=src pytest tests/test_predict.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/claude_statusbar/predict.py tests/test_predict.py
git commit -m "feat(predict): account-global sample store (dedup, prune, atomic)"
```

---

### Task 3: predict.py — `forecast_chip` + `forecast` orchestrator

**Files:**
- Modify: `src/claude_statusbar/predict.py`
- Test: `tests/test_predict.py`

- [ ] **Step 1: Write failing tests**

```python
# append to tests/test_predict.py
from claude_statusbar.predict import forecast_chip, forecast


def _hist(window, samples):
    return {window: [[t, p] for (t, p) in samples]}

def test_forecast_chip_at_risk():
    # 60%→90% over 300s = 0.1%/s; ttl=(100-90)/0.1=100s; reset is 9999s away → at risk
    hist = _hist("five_hour", [(1000.0, 60.0), (1300.0, 90.0)])
    chip = forecast_chip(hist, "five_hour", used_pct=90.0,
                         resets_at=1300.0 + 9999, now=1300.0)
    assert chip == "~1m"   # 100s → "~1m" (floored)

def test_forecast_chip_safe_when_reset_first():
    # ttl huge vs reset soon → no chip
    hist = _hist("five_hour", [(1000.0, 10.0), (1300.0, 11.0)])  # ~0.0033%/s
    chip = forecast_chip(hist, "five_hour", used_pct=11.0,
                         resets_at=1300.0 + 60, now=1300.0)  # resets in 60s
    assert chip is None

def test_forecast_chip_none_without_resets_at():
    hist = _hist("five_hour", [(1000.0, 60.0), (1300.0, 90.0)])
    assert forecast_chip(hist, "five_hour", 90.0, resets_at=None, now=1300.0) is None

def test_forecast_chip_none_insufficient_samples():
    hist = _hist("five_hour", [(1300.0, 90.0)])
    assert forecast_chip(hist, "five_hour", 90.0, resets_at=1e12, now=1300.0) is None

def test_forecast_records_and_returns_both(tmp_path, monkeypatch):
    import claude_statusbar.predict as predict
    monkeypatch.setattr(predict, "_HISTORY_PATH", tmp_path / "h.json")
    # First call seeds the history (one sample each) → no chips yet.
    c5, c7 = forecast(used_5h=50.0, resets_5h=1e12, used_7d=10.0,
                      resets_7d=1e12, now=1000.0)
    assert c5 is None and c7 is None
    # Persisted.
    assert (tmp_path / "h.json").exists()
```

- [ ] **Step 2: Run — expect FAIL**

Run: `PYTHONPATH=src pytest tests/test_predict.py -q`
Expected: FAIL

- [ ] **Step 3: Implement**

```python
# append to src/claude_statusbar/predict.py
def forecast_chip(history: dict, window: str, used_pct, resets_at,
                  now: float) -> Optional[str]:
    """Raw `~<eta>` chip string when this window is projected to hit 100% before
    it resets, else None. Pure given `history` (does NOT record/persist)."""
    try:
        used = float(used_pct)
    except (TypeError, ValueError):
        return None
    if resets_at is None:
        return None
    try:
        time_to_reset = float(resets_at) - now
    except (TypeError, ValueError):
        return None
    if time_to_reset <= 0:
        return None
    rate = burn_rate(history.get(window, []), now, LOOKBACK_S.get(window, 1800))
    ttl = time_to_limit(used, rate)
    if ttl is None or ttl >= time_to_reset:
        return None
    return format_eta(ttl)


def forecast(used_5h, resets_5h, used_7d, resets_7d, now: float):
    """Record both windows' current samples, persist once, and return
    (chip_5h, chip_7d). One read + at-most-one write per render. Never raises."""
    try:
        history = load_history()
        if used_5h is not None:
            record_sample(history, "five_hour", used_5h, now)
        if used_7d is not None:
            record_sample(history, "seven_day", used_7d, now)
        save_history(history)
        c5 = forecast_chip(history, "five_hour", used_5h, resets_5h, now)
        c7 = forecast_chip(history, "seven_day", used_7d, resets_7d, now)
        return c5, c7
    except Exception:
        return None, None
```

- [ ] **Step 4: Run — expect PASS**

Run: `PYTHONPATH=src pytest tests/test_predict.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/claude_statusbar/predict.py tests/test_predict.py
git commit -m "feat(predict): forecast_chip + forecast orchestrator (record+persist+predict)"
```

---

### Task 4: config — `show_forecast` (default on) + `cs config show`

**Files:**
- Modify: `src/claude_statusbar/config.py` (5 sites)
- Modify: `src/claude_statusbar/cli.py` (config-show listing)
- Test: `tests/test_config_activity.py` (or a new `tests/test_config_forecast.py`)

- [ ] **Step 1: Write failing test**

```python
# tests/test_config_forecast.py
from claude_statusbar.config import StatusbarConfig, load_config, set_value


def test_default_on():
    assert StatusbarConfig().show_forecast is True

def test_set_and_load(tmp_path):
    p = tmp_path / "cfg.json"
    set_value("show_forecast", "false", p)
    assert load_config(p).show_forecast is False
```

- [ ] **Step 2: Run — expect FAIL** (`AttributeError: show_forecast`)

Run: `PYTHONPATH=src pytest tests/test_config_forecast.py -q`

- [ ] **Step 3: Implement (5 sites + cli)**

In `config.py`:
- dataclass: add `show_forecast: bool = True` (next to `bar_shimmer`).
- `load_config(...)`: add `show_forecast=_to_bool(raw.get("show_forecast", True)),`.
- `VALID_KEYS`: add `"show_forecast"`.
- `_BOOL_KEYS`: add `"show_forecast"`.

In `cli.py` `config show` block, add after the `bar_shimmer` line:
```python
        print(f"show_forecast       = {cfg.show_forecast}")
```

- [ ] **Step 4: Run — expect PASS** (and `PYTHONPATH=src pytest tests/test_config.py tests/test_config_show_keys.py -q` still green; add `show_forecast` to the `test_config_show_keys` key list)

- [ ] **Step 5: Commit**

```bash
git add src/claude_statusbar/config.py src/claude_statusbar/cli.py tests/test_config_forecast.py tests/test_config_show_keys.py
git commit -m "feat(config): show_forecast flag (default on) + cs config show"
```

---

### Task 5: render — chip after `⏰reset`, colored like cache_age

**Files:**
- Modify: `src/claude_statusbar/progress.py` (`format_status_line` + a `_forecast_color` helper + 5h/7d append sites)
- Modify: `src/claude_statusbar/styles.py` (`render_classic` forwards `forecast_5h`/`forecast_7d`; `render()` dispatcher passes them through — they're already absorbed by `**kwargs`, but `render_classic` must accept + forward them)
- Test: `tests/test_forecast_render.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_forecast_render.py
from claude_statusbar.progress import format_status_line, _forecast_color, _fg
from claude_statusbar.themes import get_theme

TH = get_theme("graphite")


def test_chip_after_5h_reset_when_present():
    out = format_status_line(msgs_pct=80, tkns_pct=None, reset_time="1h28m",
                             model="Opus", weekly_pct=10, reset_time_7d="6d",
                             use_color=False, theme=TH, forecast_5h="~40m")
    assert "⏰1h28m" in out
    assert "~40m" in out
    assert out.index("~40m") > out.index("1h28m")   # after the reset

def test_chip_after_7d_reset_when_present():
    out = format_status_line(msgs_pct=10, tkns_pct=None, reset_time="1h",
                             model="Opus", weekly_pct=90, reset_time_7d="2d",
                             use_color=False, theme=TH, forecast_7d="~3h10m")
    assert out.index("~3h10m") > out.index("2d")

def test_no_chip_when_absent():
    out = format_status_line(msgs_pct=80, tkns_pct=None, reset_time="1h",
                             model="Opus", weekly_pct=10, reset_time_7d="6d",
                             use_color=False, theme=TH)
    assert "~" not in out

def test_forecast_color_tiers():
    assert _forecast_color("~30s", TH) == _fg(TH.s_hot)   # <1min → hot
    assert _forecast_color("~8m", TH) == _fg(TH.s_hot)    # ≤10min → hot
    assert _forecast_color("~40m", TH) == _fg(TH.s_warn)  # >10min → warn
    assert _forecast_color("~2h10m", TH) == _fg(TH.s_warn)  # hours → warn

def test_color_mode_chip_is_clean_when_off():
    out = format_status_line(msgs_pct=80, tkns_pct=None, reset_time="1h",
                             model="Opus", weekly_pct=10, reset_time_7d="6d",
                             use_color=False, theme=TH, forecast_5h="~8m")
    assert "\x1b" not in out
```

- [ ] **Step 2: Run — expect FAIL**

Run: `PYTHONPATH=src pytest tests/test_forecast_render.py -q`

- [ ] **Step 3: Implement**

In `progress.py`, add the helper near the other color helpers:
```python
def _forecast_color(chip: str, theme):
    """hot when ≤10 min (bare seconds, or '~Nm' with N≤10), else warn."""
    body = chip.lstrip("~")
    if "h" in body:
        return _fg(theme.s_warn)
    if body.endswith("s"):
        return _fg(theme.s_hot)
    if body.endswith("m"):
        try:
            return _fg(theme.s_hot if int(body[:-1]) <= 10 else theme.s_warn)
        except ValueError:
            return _fg(theme.s_warn)
    return _fg(theme.s_warn)
```

In `format_status_line`, add params `forecast_5h: str = ""`, `forecast_7d: str = ""`.
- After the 5h `dim_5h += colorize(f"⏰{reset_time}{countdown_emoji}", color_5h, use_color)` line, append:
```python
    if forecast_5h:
        dim_5h += " " + colorize(f"⚠{forecast_5h}", _forecast_color(forecast_5h, theme), use_color)
```
- For 7d, after the `if reset_time_7d: dim_7d += colorize(...)` block, append:
```python
    if forecast_7d:
        dim_7d += " " + colorize(f"⚠{forecast_7d}", _forecast_color(forecast_7d, theme), use_color)
```

In `styles.py` `render_classic`: add params `forecast_5h="", forecast_7d=""` and pass them into the `format_status_line(...)` call. (The `render()` dispatcher already forwards unknown kwargs to the renderer via `**kwargs`, so no dispatcher change is needed beyond ensuring these reach `render_classic`.)

- [ ] **Step 4: Run — expect PASS** (+ `PYTHONPATH=src pytest tests/test_progress.py tests/test_styles.py -q` still green)

- [ ] **Step 5: Commit**

```bash
git add src/claude_statusbar/progress.py src/claude_statusbar/styles.py tests/test_forecast_render.py
git commit -m "feat(render): forecast chip after reset timer, colored by urgency"
```

---

### Task 6: wire `core.main` (lazy import + guard + plumb)

**Files:**
- Modify: `src/claude_statusbar/core.py` (official-data render branch)
- Test: `tests/test_core_forecast_guard.py`

- [ ] **Step 1: Write failing test** (degradation guard + opt-out)

```python
# tests/test_core_forecast_guard.py
import io, json, sys


def test_main_survives_forecast_exception(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".claude").mkdir(parents=True)
    (tmp_path / ".claude" / "claude-statusbar.json").write_text(
        json.dumps({"show_forecast": True, "show_project_branch": False,
                    "show_cache_age": False, "show_todos": False}),
        encoding="utf-8")
    import claude_statusbar.predict as predict
    monkeypatch.setattr(predict, "forecast",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    payload = json.dumps({
        "session_id": "x", "transcript_path": "/n.jsonl",
        "model": {"id": "o", "display_name": "Opus 4.8"},
        "rate_limits": {"five_hour": {"used_percentage": 80, "resets_at": 9999999999},
                        "seven_day": {"used_percentage": 5, "resets_at": 9999999999}}})
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    from claude_statusbar.core import main
    main(use_color=False, _suppress_side_effects=True)
    assert "Opus 4.8" in capsys.readouterr().out   # bar still rendered, no blank


def test_chip_appears_when_forecast_returns_one(tmp_path, monkeypatch, capsys):
    # True RED→GREEN: a non-throwing forecast returning a chip must reach the bar.
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".claude").mkdir(parents=True)
    (tmp_path / ".claude" / "claude-statusbar.json").write_text(
        json.dumps({"show_forecast": True, "show_project_branch": False,
                    "show_cache_age": False, "show_todos": False}),
        encoding="utf-8")
    import claude_statusbar.predict as predict
    monkeypatch.setattr(predict, "forecast", lambda *a, **k: ("~8m", ""))
    payload = json.dumps({
        "session_id": "x", "transcript_path": "/n.jsonl",
        "model": {"id": "o", "display_name": "Opus 4.8"},
        "rate_limits": {"five_hour": {"used_percentage": 88, "resets_at": 9999999999},
                        "seven_day": {"used_percentage": 5, "resets_at": 9999999999}}})
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    from claude_statusbar.core import main
    main(use_color=False, _suppress_side_effects=True)
    assert "~8m" in capsys.readouterr().out   # chip plumbed to the bar
```

- [ ] **Step 2: Run — expect FAIL** (forecast not wired / `predict.forecast` not used yet → exception not relevant → assert may pass trivially; first make it RED by asserting a chip appears for an at-risk payload using a real temp history — OPTIONAL. The guard test above is the key safety test.)

Run: `PYTHONPATH=src pytest tests/test_core_forecast_guard.py -q`

- [ ] **Step 3: Implement in `core.main`**

**Location:** inside `if has_official:` → the **non-json** sub-branch (the `else:`
of `if json_output:`), right before that branch's `print(_render_style(...))`.
Do **not** put it under `if json_output:` or at the top of `if has_official:`
(that would run on every `cs --json` and record samples needlessly). Add
`**forecast_kwargs,` only to the **non-json official** `_render_style(...)` call.

Code:
```python
    forecast_kwargs = {}
    if cfg.show_forecast:
        try:
            import time as _t
            from .predict import forecast
            f5, f7 = forecast(
                used_5h=stdin_data.get("rate_limit_pct"),
                resets_5h=stdin_data.get("rate_limit_resets_at"),
                used_7d=stdin_data.get("rate_limit_7d_pct"),
                resets_7d=stdin_data.get("rate_limit_7d_resets_at"),
                now=_t.time(),
            )
            forecast_kwargs = {"forecast_5h": f5 or "", "forecast_7d": f7 or ""}
        except Exception:
            forecast_kwargs = {}
```
Add `**forecast_kwargs,` to the official-branch `_render_style(...)` call (alongside `**identity_kwargs, **activity_kwargs,`). (The "waiting"/no-rate-limit branch has no pcts, so skip it there.)

- [ ] **Step 4: Run — expect PASS**

Run: `PYTHONPATH=src pytest tests/test_core_forecast_guard.py -q`
Then the import-perf invariant: `PYTHONPATH=src pytest tests/test_import_perf.py -q` (predict is lazy-imported → must stay green).

- [ ] **Step 5: Commit**

```bash
git add src/claude_statusbar/core.py tests/test_core_forecast_guard.py
git commit -m "feat(core): wire forecast chip (lazy import, guarded, official-data branch)"
```

---

### Task 7: full suite + preview eyeball + docs

**Files:**
- Modify: `README.md` (config table row + cheatsheet + Latest-release note for next version), `src/claude_statusbar/skills/claude-statusbar/SKILL.md` (toggle row), `CHANGELOG.md`.

- [ ] **Step 1: Full suite**

Run: `PYTHONPATH=src pytest -q` — expect all green. Also `python3 -m py_compile src/claude_statusbar/*.py`.

- [ ] **Step 2: Eyeball at-risk render**

```bash
PYTHONPATH=src python3 -c "
from claude_statusbar.progress import format_status_line
from claude_statusbar.themes import get_theme
print(format_status_line(msgs_pct=88, tkns_pct=None, reset_time='1h28m', model='Opus 4.8', weekly_pct=61, reset_time_7d='5d18h', ctx_pct=35.0, use_color=True, theme=get_theme('graphite'), forecast_5h='~8m'))
"
```
Expected: `5h[…88%…]⏰1h28m ⚠~8m | 7d[…]⏰5d18h …` with `⚠~8m` in red (≤10min).

- [ ] **Step 3: Docs**

- README config table: add a `show_forecast` row (default `true`; describes the `⚠~40m` at-risk chip; only shows when projected to exhaust before reset).
- README cheatsheet: `cs config set show_forecast false  # hide the at-risk forecast chip`.
- SKILL.md: `| Toggle the at-risk forecast chip | \`cs config set show_forecast true\|false\` (default on) |` + add keyword "forecast / 预测 / 还能用多久".
- CHANGELOG: add a `### Added` bullet under the next version's section.

- [ ] **Step 4: Commit**

```bash
git add README.md src/claude_statusbar/skills/claude-statusbar/SKILL.md CHANGELOG.md
git commit -m "docs(forecast): document show_forecast (at-risk rate-limit chip)"
```

---

## Notes for the implementer

- **Run tests with `PYTHONPATH=src`** (the package isn't installed for the default python in this repo).
- **Fail-safe is the contract:** every public `predict` entry returns `None`/empty and never raises; `core.main` wraps the call in `try/except`. A bug here must degrade to "no chip", never a blank bar.
- **Hot-path discipline:** `predict` is lazy-imported inside the `show_forecast` branch only — keep `test_import_perf.py` green (no `subprocess`/`shutil`/`importlib.metadata`).
- **Account-global store:** `rate_history.json` is shared across windows on purpose (quota is account-level). Concurrent last-writer-wins is acceptable (estimate).
- **After all tasks:** reinstall (`uv tool install . --reinstall`) to dogfdood live, then this becomes part of the next release (`release: vX.Y.Z`) — version bump is a separate release step, not in this plan.
