"""Small ANSI-aware display-width helpers shared by render paths."""
import os
import re
import unicodedata
from typing import Mapping, Optional

_ANSI_RE = re.compile(
    r"\x1b(?:"
    r"\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC
    r"|\[[0-?]*[ -/]*[@-~]"             # CSI
    r"|[ -/]*[@-~]"                      # other ESC sequence
    r")"
)
_SGR_RE = re.compile(r"\x1b\[([0-9;:]*)m")
_RESET = "\x1b[0m"
_OSC8_RE = re.compile(r"\x1b\]8;[^;\x07\x1b]*;([^\x07\x1b]*)(?:\x07|\x1b\\)")
_LINK_CLOSE = "\x1b]8;;\x07"
_SAFE_URL_RE = re.compile(r"https?://[!-~]+")


def hyperlink(text: str, url: Optional[str]) -> str:
    """OSC 8 link (Cmd/Ctrl+click in terminals that support it; Claude Code
    passes it through). BEL-terminated, as Claude Code's statusline docs show.
    Anything but a plain printable http(s) URL leaves the text unlinked."""
    if not url or not _SAFE_URL_RE.fullmatch(url):
        return text
    return f"\x1b]8;;{url}\x07{text}{_LINK_CLOSE}"


def _link_open(open_: bool, sequence: str) -> bool:
    match = _OSC8_RE.fullmatch(sequence)
    if match is None:
        return open_
    return bool(match.group(1))


def terminal_width(env: Optional[Mapping[str, str]] = None) -> Optional[int]:
    """Positive COLUMNS from env, terminal size, or None when unavailable."""
    source = os.environ if env is None else env
    raw = source.get("COLUMNS")
    try:
        width = int(str(raw).strip())
    except (TypeError, ValueError):
        width = 0
    if width > 0:
        return width
    try:
        width = os.get_terminal_size().columns
    except OSError:
        return None
    return width if width > 0 else None


def _char_width(char: str) -> int:
    if unicodedata.combining(char):
        return 0
    category = unicodedata.category(char)
    if category in {"Cf", "Cc", "Cs"}:
        return 0
    return 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1


def visible_width(text: str) -> int:
    """Terminal-cell width, excluding ANSI control sequences."""
    width = 0
    pos = 0
    for match in _ANSI_RE.finditer(text):
        width += sum(_char_width(char) for char in text[pos:match.start()])
        pos = match.end()
    return width + sum(_char_width(char) for char in text[pos:])


def _sgr_active(active: bool, sequence: str) -> bool:
    match = _SGR_RE.fullmatch(sequence)
    if match is None:
        return active
    params = match.group(1)
    if not params:
        return False
    reset_codes = {"", "22", "23", "24", "25", "27", "28", "29", "39", "49"}
    for value in params.replace(":", ";").split(";"):
        if value == "0":
            active = False
        elif value not in reset_codes:
            active = True
    return active


def clip_line(text: str, max_width: Optional[int], ellipsis: str = "…") -> str:
    """Clip one physical line without splitting ANSI sequences."""
    if max_width is None or visible_width(text) <= max_width:
        return text
    if max_width <= 0:
        return ""

    ellipsis_width = visible_width(ellipsis)
    if ellipsis_width > max_width:
        return ""
    content_limit = max_width - ellipsis_width
    output = []
    used = 0
    active_sgr = False
    link_open = False
    pos = 0

    def _close(clipped: str) -> str:
        # A link cut mid-way must be closed, or everything the terminal prints
        # after the status line becomes part of it.
        return (clipped + (_LINK_CLOSE if link_open else "")
                + (_RESET if active_sgr else ""))

    for match in _ANSI_RE.finditer(text):
        for char in text[pos:match.start()]:
            char_width = _char_width(char)
            if used + char_width > content_limit:
                return _close("".join(output) + ellipsis)
            output.append(char)
            used += char_width
        sequence = match.group(0)
        output.append(sequence)
        active_sgr = _sgr_active(active_sgr, sequence)
        link_open = _link_open(link_open, sequence)
        pos = match.end()

    for char in text[pos:]:
        char_width = _char_width(char)
        if used + char_width > content_limit:
            return _close("".join(output) + ellipsis)
        output.append(char)
        used += char_width

    return text


def clip_lines(text: str, max_width: Optional[int]) -> str:
    """Clip each physical line independently, preserving line endings."""
    if max_width is None or not text:
        return text
    output = []
    for part in text.splitlines(keepends=True):
        if part.endswith("\r\n"):
            line, ending = part[:-2], "\r\n"
        elif part.endswith(("\n", "\r")):
            line, ending = part[:-1], part[-1:]
        else:
            line, ending = part, ""
        output.append(clip_line(line, max_width) + ending)
    return "".join(output)
