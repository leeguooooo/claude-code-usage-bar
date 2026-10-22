"""`cs theme` — pick one of the three looks with a live preview.

Arrow keys (or j/k, or 1-3) move, Enter applies, q / Esc / Ctrl-C cancels.
Without a terminal it just prints the looks and how to switch. On Windows
(no termios) it falls back to typing a number.
"""

import os
import sys
from typing import Optional

# (key, style, bar_glyph, label key, command)
LOOKS = [
    ("block", "aurora", "block", "label_block", "cs config set bar_glyph block"),
    ("thin", "aurora", "thin", "label_thin", "cs config set bar_glyph thin"),
    ("classic", "classic", "block", "label_classic", "cs config set style classic"),
]

TEXT = {
    "title":         {"zh": "选择状态栏外观", "en": "Pick a status-bar look"},
    "keys":          {"zh": "↑/↓ 或 1-3 选择 · 回车应用 · q 取消",
                      "en": "↑/↓ or 1-3 to move · Enter to apply · q to cancel"},
    "current":       {"zh": "← 当前", "en": "← current"},
    "label_block":   {"zh": "Aurora 方块（默认）", "en": "Aurora, block bars (default)"},
    "label_thin":    {"zh": "Aurora 细线", "en": "Aurora, thin line"},
    "label_classic": {"zh": "Classic 原版", "en": "Classic"},
    "prompt":        {"zh": "输入 1-3 应用（回车取消）：", "en": "Type 1-3 to apply (Enter cancels): "},
    "cancelled":     {"zh": "已取消，外观没变。", "en": "Cancelled — look unchanged."},
    "unchanged":     {"zh": "没变，还是当前这个。", "en": "No change — that's already the current look."},
    "applied":       {"zh": "已切换到 {label}，状态栏下一次刷新就生效。",
                      "en": "Switched to {label}. The status bar picks it up on its next refresh."},
}
_lang = "en"


def t(key: str, **kw) -> str:
    return TEXT[key][_lang].format(**kw)

GOLD = "\033[38;2;212;175;55m\033[1m"
DIM = "\033[38;2;110;110;115m"
OK = "\033[38;2;120;200;192m"
R = "\033[0m"


def current_look(cfg) -> str:
    if cfg.style == "classic":
        return "classic"
    return "thin" if cfg.bar_glyph == "thin" else "block"


def _preview_lines(use_color: bool, width: Optional[int]) -> list:
    from .preview import _real_data, _demo_data
    from .styles import render
    from .themes import get_theme
    data = _real_data() or _demo_data()
    lines = []
    for _key, style, glyph, _label, _cmd in LOOKS:
        out = render(
            style, theme=get_theme("graphite"), bar_glyph=glyph,
            msgs_pct=data["msgs_pct"], weekly_pct=data["weekly_pct"],
            reset_5h=data["reset_5h"], reset_7d=data["reset_7d"],
            model=data["model"], cost_text=data.get("cost_text", ""),
            cache_age_text=data.get("cache_age_text", ""),
            use_color=use_color, max_width=width,
            warning_threshold=30.0, critical_threshold=70.0,
        )
        lines.append(out.split("\n", 1)[0])
    return lines


def _frame(sel: int, cur: str, previews: list, color: bool) -> list:
    g, d, ok, r = (GOLD, DIM, OK, R) if color else ("", "", "", "")
    rows = [f"{g}{t('title')}{r}  {d}{t('keys')}{r}", ""]
    for i, (key, _s, _g, label_key, _c) in enumerate(LOOKS):
        label = t(label_key)
        mark = f" {ok}{t('current')}{r}" if key == cur else ""
        if i == sel:
            rows.append(f"{g}› {i + 1}  {label}{r}{mark}")
        else:
            rows.append(f"  {d}{i + 1}{r}  {label}{mark}")
        rows.append(f"     {previews[i]}")
        rows.append("")
    return rows


def apply(key: str) -> None:
    from . import config as cfg_mod
    for k, style, glyph, _l, _c in LOOKS:
        if k == key:
            cfg_mod.set_value("style", style)
            if style == "aurora":
                cfg_mod.set_value("bar_glyph", glyph)
            return


def _read_key(fd) -> str:
    ch = os.read(fd, 1)
    if ch == b"\x1b":
        import select
        if not select.select([fd], [], [], 0.05)[0]:
            return "esc"
        seq = os.read(fd, 2)
        return {b"[A": "up", b"[B": "down", b"OA": "up", b"OB": "down"}.get(seq, "")
    return {b"\r": "enter", b"\n": "enter", b"k": "up", b"j": "down",
            b"q": "esc", b"\x03": "esc"}.get(ch, ch.decode("utf-8", "ignore"))


def _interactive(cur: str, previews: list, color: bool) -> Optional[str]:
    import termios
    import tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    sel = next(i for i, lk in enumerate(LOOKS) if lk[0] == cur)
    drawn = 0
    out = sys.stdout
    try:
        tty.setcbreak(fd)
        out.write("\033[?25l")
        while True:
            if drawn:
                out.write(f"\033[{drawn}F\033[J")
            rows = _frame(sel, cur, previews, color)
            out.write("\n".join(rows) + "\n")
            out.flush()
            drawn = len(rows)
            key = _read_key(fd)
            if key == "up":
                sel = (sel - 1) % len(LOOKS)
            elif key == "down":
                sel = (sel + 1) % len(LOOKS)
            elif key in ("1", "2", "3"):
                sel = int(key) - 1
            elif key == "enter":
                return LOOKS[sel][0]
            elif key == "esc":
                return None
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        out.write("\033[?25h")
        out.flush()


def _numbered(cur: str, previews: list, color: bool) -> Optional[str]:
    print("\n".join(_frame(-1, cur, previews, color)))
    try:
        ans = input(t("prompt")).strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if ans in ("1", "2", "3"):
        return LOOKS[int(ans) - 1][0]
    return None


def run(no_color: bool = False) -> int:
    global _lang
    from . import config as cfg_mod
    from ._display import terminal_width
    from .i18n import ui_lang
    cfg = cfg_mod.load_config()
    _lang = ui_lang(cfg.lang)
    cur = current_look(cfg)
    interactive = sys.stdin.isatty() and sys.stdout.isatty()
    color = not no_color and "NO_COLOR" not in os.environ and sys.stdout.isatty()
    width = terminal_width(os.environ)
    previews = _preview_lines(color, width - 5 if width else None)

    if not interactive:
        d, r = (DIM, R) if color else ("", "")
        for i, (key, _s, _g, label_key, cmd) in enumerate(LOOKS):
            mark = f"  {t('current')}" if key == cur else ""
            print(f"{i + 1}  {t(label_key)}{mark}  {d}{cmd}{r}")
            print(f"   {previews[i]}")
        return 0

    try:
        import termios  # noqa: F401
        pick = _interactive(cur, previews, color)
    except ImportError:
        pick = _numbered(cur, previews, color)

    if pick is None:
        print(t("cancelled"))
        return 0
    if pick == cur:
        print(t("unchanged"))
        return 0
    apply(pick)
    label = t(next(lk[3] for lk in LOOKS if lk[0] == pick))
    print(t("applied", label=label))
    return 0
