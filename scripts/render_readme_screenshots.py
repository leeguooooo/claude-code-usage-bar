#!/usr/bin/env python3
"""Regenerate the README screenshots in docs/images/look-*.png.

Renders the three looks (aurora block, aurora thin, classic) from fixed demo
data in an isolated HOME, then captures each one in a real terminal with vhs
so colors and emoji match what users see. Needs `vhs` and `ffmpeg` on PATH.

    uv run python scripts/render_readme_screenshots.py

The same script lives in claude-code-usage-bar and codex-statebar; it detects
which package it is running in.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "images"
IS_CODEX = (ROOT / "src" / "codex_statebar").is_dir()
CLI = Path(sys.executable).parent / ("cxs" if IS_CODEX else "cs")
LOOKS = {
    "aurora": [("style", "aurora"), ("bar_glyph", "block")],
    "thin": [("style", "aurora"), ("bar_glyph", "thin")],
    "classic": [("style", "classic")],
}
# Terminal size per tool: Claude shows two lines, Codex three (effort line).
WIDTH, HEIGHT = (800, 138) if IS_CODEX else (1270, 112)
THEME = {
    "background": "#1c1f26", "foreground": "#dcdcdc", "cursor": "#1c1f26",
    "selection": "#333333",
    "black": "#1c1f26", "red": "#e87474", "green": "#4ec85b", "yellow": "#e8ac61",
    "blue": "#6aa6e8", "magenta": "#c886ab", "cyan": "#5fb8c2", "white": "#dcdcdc",
    "brightBlack": "#4b5058", "brightRed": "#e87474", "brightGreen": "#4ec85b",
    "brightYellow": "#e8ac61", "brightBlue": "#6aa6e8", "brightMagenta": "#c886ab",
    "brightCyan": "#5fb8c2", "brightWhite": "#ffffff",
}


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=demo", "-c", "user.email=demo@example.com",
                    *args], cwd=cwd, check=True, capture_output=True)


def demo_repo(base: Path) -> Path:
    """`my-app` with a dirty `feat/login` worktree, so the worktree line shows."""
    main = base / "src" / "my-app"
    main.mkdir(parents=True)
    git(main, "init", "-q", "-b", "main")
    git(main, "commit", "-q", "--allow-empty", "-m", "init")
    worktree = base / "src" / "my-app-login"
    git(main, "worktree", "add", "-q", "-b", "feat/login", str(worktree))
    (worktree / "login.py").write_text("print('hi')\n")
    return worktree


def demo_input(base: Path, home: Path, cwd: Path) -> Path:
    now = int(time.time())
    path = base / "input.json"
    if IS_CODEX:
        thread = "0199demo-0000-7000-8000-000000000001"
        rollout = home / ".codex" / "sessions" / "2026" / "01" / "01" / (
            f"rollout-2026-01-01T12-00-00-{thread}.jsonl")
        rollout.parent.mkdir(parents=True)
        events = [
            {"type": "session_meta", "payload": {
                "id": thread, "cwd": str(cwd), "cli_version": "0.164.0",
                "source": "cli", "originator": "codex-tui"}},
            {"type": "turn_context", "payload": {
                "model": "gpt-5.6", "effort": "high", "approval_policy": "on-request",
                "sandbox_policy": {"type": "workspace-write"}}},
            {"type": "event_msg", "payload": {
                "type": "token_count",
                "info": {"model_context_window": 353400, "last_token_usage": {
                    "input_tokens": 96000, "cached_input_tokens": 40000,
                    "output_tokens": 2000, "total_tokens": 98000}},
                "rate_limits": {"plan_type": "pro",
                                "primary": {"used_percent": 47, "window_minutes": 300,
                                            "resets_at": now + 10020},
                                "secondary": {"used_percent": 61, "window_minutes": 10080,
                                              "resets_at": now + 172800}}}},
        ]
        rollout.write_text("".join(json.dumps(event) + "\n" for event in events))
        payload = {"rollout_path": str(rollout), "thread_id": thread,
                   "cwd": str(cwd), "codex_version": "0.164.0"}
    else:
        payload = {
            "session_id": "demo-0001", "transcript_path": "", "cwd": str(cwd),
            "workspace": {"current_dir": str(cwd), "project_dir": str(cwd)},
            "model": {"id": "claude-opus-5-5", "display_name": "Opus 5.5"},
            "version": "2.1.310",
            "cost": {"total_cost_usd": 3.42, "total_duration_ms": 2580000,
                     "total_lines_added": 184, "total_lines_removed": 37},
            "context_window": {"context_window_size": 1000000, "used_percentage": 18,
                               "total_input_tokens": 180000,
                               "current_usage": {"input_tokens": 180000}},
            # Usage high enough that the bars show the green → amber gradient.
            "rate_limits": {
                "five_hour": {"used_percentage": 64, "resets_at": now + 4200},
                "seven_day": {"used_percentage": 41, "resets_at": now + 259200}},
        }
    path.write_text(json.dumps(payload))
    return path


def render(look: str, home: Path, payload: Path, env: dict) -> str:
    for key, value in LOOKS[look]:
        subprocess.run([str(CLI), "config", "set", key, value], env=env,
                       check=True, capture_output=True)
    shutil.rmtree(home / ".cache", ignore_errors=True)
    run = lambda: subprocess.run([str(CLI)], stdin=payload.open(), env=env,
                                 check=True, capture_output=True, text=True).stdout
    run()  # first render starts the async git refresh (dirty marker)
    time.sleep(1.5)
    return run().rstrip("\n")


def capture(name: str, ansi: str, work: Path) -> Path:
    (work / f"{name}.ansi").write_text(ansi)
    # vhs types the command, so keep escapes out of the tape itself.
    (work / "show.sh").write_text(
        "#!/bin/bash\nprintf '\\033[?25l\\033[2J\\033[H'\ncat \"$1.ansi\"\nsleep 30\n")
    tape = work / f"{name}.tape"
    tape.write_text("\n".join([
        f"Output {name}.gif",
        'Set Shell "bash"',
        "Set FontSize 20",
        f"Set Width {WIDTH}",
        f"Set Height {HEIGHT}",
        "Set Padding 22",
        f"Set Theme {json.dumps(THEME)}",
        "Hide",
        f'Type "PS1= PATH=/usr/bin:/bin bash show.sh {name}"',
        "Enter",
        "Sleep 800ms",
        "Show",
        "Sleep 200ms",
        "",
    ]))
    subprocess.run(["vhs", tape.name], cwd=work, check=True, capture_output=True)
    png = work / f"{name}.png"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-sseof", "-0.1",
                    "-i", f"{name}.gif", "-frames:v", "1", "-update", "1", png.name],
                   cwd=work, check=True)
    return png


def main() -> int:
    missing = [tool for tool in ("vhs", "ffmpeg", "git") if not shutil.which(tool)]
    if missing or not CLI.exists():
        print(f"missing: {', '.join(missing) or CLI}", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory(prefix="readme-shots-") as tmp:
        base = Path(tmp)
        home = base / "home"
        home.mkdir()
        env = {**os.environ, "HOME": str(home), "CODEX_HOME": str(home / ".codex"),
               "COLUMNS": "110", "CODEX_STATEBAR_NO_UPDATE": "1",
               "CLAUDE_STATUSBAR_NO_UPDATE": "1"}
        subprocess.run([str(CLI), "config", "set", "looks_seen", "1"], env=env,
                       check=True, capture_output=True)
        payload = demo_input(base, home, demo_repo(base))
        OUT.mkdir(parents=True, exist_ok=True)
        for look in LOOKS:
            ansi = render(look, home, payload, env)
            print(f"{look}: {re.sub(chr(27) + r'\[[0-9;]*m', '', ansi)}")
            shutil.copy(capture(f"look-{look}", ansi, base), OUT / f"look-{look}.png")
    print(f"wrote {OUT}/look-{{{','.join(LOOKS)}}}.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
