import os

from claude_statusbar import _display


def test_terminal_width_prefers_positive_columns(monkeypatch):
    monkeypatch.setattr(_display.os, "get_terminal_size", lambda: os.terminal_size((80, 24)))
    assert _display.terminal_width({"COLUMNS": "42"}) == 42


def test_terminal_width_falls_back_to_terminal(monkeypatch):
    monkeypatch.setattr(_display.os, "get_terminal_size", lambda: os.terminal_size((80, 24)))
    for value in (None, "", "0", "-1", "nope"):
        assert _display.terminal_width({"COLUMNS": value}) == 80


def test_terminal_width_unavailable(monkeypatch):
    def unavailable():
        raise OSError

    monkeypatch.setattr(_display.os, "get_terminal_size", unavailable)
    assert _display.terminal_width({}) is None


def test_terminal_width_defaults_to_process_env(monkeypatch):
    monkeypatch.setenv("COLUMNS", "53")
    assert _display.terminal_width() == 53


def test_visible_width_ignores_ansi_and_counts_unicode_cells():
    assert _display.visible_width("\x1b[31mred\x1b[0m") == 3
    assert _display.visible_width("A界B") == 4
    assert _display.visible_width("é") == 1
    assert _display.visible_width("A‍B") == 2


def test_clip_line_plain_and_tiny_limits():
    assert _display.clip_line("abcdef", 4) == "abc…"
    assert _display.clip_line("abcdef", 1) == "…"
    assert _display.clip_line("abcdef", 0) == ""
    assert _display.clip_line("abc", 3) == "abc"


def test_clip_line_does_not_split_wide_or_combining_characters():
    assert _display.clip_line("A界BC", 4) == "A界…"
    assert _display.clip_line("éxyz", 3) == "éx…"


def test_clip_line_preserves_ansi_and_resets_active_color():
    clipped = _display.clip_line("\x1b[31mabcdef", 4)
    assert clipped == "\x1b[31mabc…\x1b[0m"
    assert _display.visible_width(clipped) == 4
    assert not _display.clip_line("\x1b[31;0mabcdef", 4).endswith("\x1b[0m")


def test_clip_lines_preserves_boundaries_and_trailing_newline():
    text = "abcdef\nxy\r\n12345\n"
    assert _display.clip_lines(text, 4) == "abc…\nxy\r\n123…\n"
