"""narrow_layout=stack (#73): a too-wide line 1 re-flows instead of dropping."""

import time
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_statusbar import config
from claude_statusbar._display import visible_width
from claude_statusbar.styles import RENDERERS, render
from claude_statusbar.themes import get_theme

SAMPLE = dict(
    msgs_pct=41, weekly_pct=35,
    reset_5h="3h54m", reset_7d="5d11h",
    model="Opus 5.5(583.0k/1.0M)",
    lang_body="EN:6.0↑", cost_text="12.34", cache_age_text="4m23s",
    projection_5h="→100%·1h40m", projection_7d="→100%·2d15h",
    warning_threshold=30.0, critical_threshold=70.0,
)


def _render(style, width, layout="stack", use_color=False, **extra):
    return render(style, theme=get_theme("graphite"), use_color=use_color,
                  max_width=width, narrow_layout=layout, **{**SAMPLE, **extra})


@pytest.mark.parametrize("style", list(RENDERERS))
@pytest.mark.parametrize("use_color", [False, True])
def test_stack_at_70_keeps_every_segment(style, use_color):
    out = _render(style, 70, use_color=use_color)
    lines = out.split("\n")
    assert all(visible_width(line) <= 70 for line in lines)
    plain = _render(style, 70)
    for text in ("→100%·1h40m", "→100%·2d15h", "583.0k/1.0M", "12.34",
                 "EN:6.0↑", "4m23s"):
        assert text in plain
    # bars lead; the model moved off their row
    rows = plain.split("\n")
    assert rows[0].lstrip().startswith("5h")
    assert "583.0k" not in rows[0]
    assert rows.index(next(r for r in rows if "7d" in r)) < rows.index(
        next(r for r in rows if "583.0k" in r))


@pytest.mark.parametrize("style", list(RENDERERS))
def test_stack_at_40_fits_and_keeps_model_cost_cache(style):
    out = _render(style, 40)
    assert all(visible_width(line) <= 40 for line in out.split("\n"))
    for text in ("5h", "7d", "583.0k/1.0M", "12.34", "EN:6.0↑", "4m23s"):
        assert text in out
    assert "…" not in out  # re-flowed, not clipped


@pytest.mark.parametrize("style", list(RENDERERS))
def test_drop_stays_the_default(style):
    kwargs = dict(theme=get_theme("graphite"), use_color=False, max_width=70,
                  **SAMPLE)
    assert render(style, **kwargs) == render(style, narrow_layout="drop", **kwargs)
    assert "→100%·1h40m" not in render(style, **kwargs)


@pytest.mark.parametrize("style", list(RENDERERS))
def test_stack_is_noop_when_line_fits(style):
    kwargs = dict(theme=get_theme("graphite"), use_color=False, **SAMPLE)
    assert render(style, max_width=500, narrow_layout="stack", **kwargs) \
        == render(style, **kwargs)


@pytest.mark.parametrize("style", list(RENDERERS))
def test_bars_share_a_row_when_they_fit_together(style):
    # Wide enough for 5h + 7d side by side, not for the whole line.
    bars = _render(style, 500, model="M", lang_body="", cost_text="",
                   cache_age_text="").split("\n")[0]
    width = visible_width(bars.rsplit(" ", 2)[0]) + 2
    out = _render(style, width, model="M", lang_body="", cost_text="",
                  cache_age_text="")
    first = out.split("\n")[0]
    assert "5h" in first and "7d" in first


@pytest.mark.parametrize("style", list(RENDERERS))
def test_per_model_bars_join_the_stack_right_aligned(style):
    limits = [dict(label="Fable", percent=20, resets_at=time.time() + 3 * 86400)]
    out = _render(style, 70, per_model_limits=limits).split("\n")
    assert out[0].startswith("   5h")
    assert out[1].startswith("   7d")
    assert out[2].startswith("Fable")
    assert all(visible_width(line) <= 70 for line in out)


def test_narrow_layout_config_key(tmp_path: Path):
    p = tmp_path / "config.json"
    assert config.StatusbarConfig().narrow_layout == "drop"
    assert config.set_value("narrow_layout", "stack", p).narrow_layout == "stack"
    assert config.load_config(p).narrow_layout == "stack"
    with pytest.raises(ValueError):
        config.set_value("narrow_layout", "wrap", p)
    assert "narrow_layout" in config.VALID_KEYS


@pytest.mark.parametrize("style", list(RENDERERS))
@pytest.mark.parametrize("use_color", [False, True])
def test_per_model_projection_degrades_with_the_other_bars(style, use_color):
    # A long per-model ETA chip must not survive while 5h/7d lose theirs.
    limits = [dict(label="Fable", percent=10, resets_at=1_561_600)]
    with patch("claude_statusbar.scoped_usage.time.time", return_value=1_000_000):
        out = _render(style, 40, use_color=use_color, per_model_limits=limits,
                      reset_7d="6d12h", ctx_pct=58.3,
                      projection_5h="→60%", projection_7d="→60%")
    assert all(visible_width(line) <= 40 for line in out.split("\n"))
    assert "…" not in out


@pytest.mark.parametrize("style", list(RENDERERS))
def test_drop_keeps_the_per_model_row_while_degrading(style):
    limits = [dict(label="Fable", percent=20, resets_at=time.time() + 3 * 86400)]
    out = _render(style, 70, layout="drop", per_model_limits=limits)
    assert out.split("\n")[1].startswith("Fable")


@pytest.mark.parametrize("style", list(RENDERERS))
def test_long_language_row_does_not_strip_rows_that_fit(style):
    out = _render(style, 32, model="Sonnet 4.6(583.0k/1.0M)",
                  projection_5h="→60%", projection_7d="→60%",
                  cost_text="", cache_age_text="",
                  lang_body="ZH:6.0↑ EN:6.0↑ FR:6.0↑ JA:6.0↑")
    assert out.count("→60%") == 2
    assert "583.0k/1.0M" in out


@pytest.mark.parametrize("style", list(RENDERERS))
@pytest.mark.parametrize("use_color", [False, True])
def test_long_scoped_row_preserves_fitting_first_line(style, use_color):
    limits = [dict(label="Model" + str(i), percent=20,
                   resets_at=time.time() + 3 * 86400) for i in range(8)]
    first = _render(style, 500, use_color=use_color).splitlines()[0]
    width = visible_width(first)
    rows = _render(style, width, use_color=use_color,
                   per_model_limits=limits).splitlines()
    assert rows[0] == first
    assert len(rows) == 1 + len(limits)
    assert all(visible_width(row) <= width for row in rows)
