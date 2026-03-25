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
