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


def test_projection_after_reset_before_eta():
    out = format_status_line(
        msgs_pct=80,
        tkns_pct=None,
        reset_time="1h28m",
        model="Opus",
        weekly_pct=10,
        reset_time_7d="6d",
        use_color=False,
        theme=TH,
        projection_5h="→92%",
        forecast_5h="~40m",
    )
    assert out.index("→92%") > out.index("1h28m")
    assert out.index("→92%") < out.index("~40m")


def test_projection_after_7d_reset():
    out = format_status_line(
        msgs_pct=10,
        tkns_pct=None,
        reset_time="1h",
        model="Opus",
        weekly_pct=30,
        reset_time_7d="6d05h",
        use_color=False,
        theme=TH,
        projection_7d="→67%",
    )
    assert out.index("→67%") > out.index("6d05h")


def test_no_projection_when_absent():
    out = format_status_line(
        msgs_pct=10,
        tkns_pct=None,
        reset_time="1h",
        model="Opus",
        weekly_pct=30,
        reset_time_7d="6d05h",
        use_color=False,
        theme=TH,
    )
    assert "→" not in out
