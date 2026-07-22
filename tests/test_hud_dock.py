"""Unit tests for the desktop HUD dock geometry (pure functions, no pyobjc).

Coordinate model: windows are (num, x, y, cw, ch) in CG top-left pixels;
`sh` is the primary-screen height used to flip into cocoa (bottom-left) space.
A window at CG (x=0, y=0, 1000x800) with sh=900 has cocoa edges
left=0 right=1000 bottom=100 top=900.
"""
from claude_statusbar.hud_data import dock_origin, detect_dock

SH, MARGIN = 22, 14
DOCK = 48
PW = PH = DOCK + 2 * SH
WIN = (0, 0, 1000, 800)   # x, y, cw, ch (CG top-left)
SCREEN_H = 900            # cocoa: window bottom=100, top=900, left=0, right=1000
CB, CT, CL, CR = 100, 900, 0, 1000


def _content_edges(ox, oy):
    return (ox + SH, oy + SH, ox + PW - SH, oy + PH - SH)  # l, b, r, t


def test_dock_origin_right_edge_hugs_window_right():
    ox, oy = dock_origin({"edge": "r", "along": 0.5}, WIN, SCREEN_H, PW, PH, SH, MARGIN)
    _, _, cont_r, _ = _content_edges(ox, oy)
    assert abs(cont_r - (CR - MARGIN)) < 0.01


def test_dock_origin_left_edge_hugs_window_left():
    ox, oy = dock_origin({"edge": "l", "along": 0.5}, WIN, SCREEN_H, PW, PH, SH, MARGIN)
    cont_l, _, _, _ = _content_edges(ox, oy)
    assert abs(cont_l - (CL + MARGIN)) < 0.01


def test_dock_origin_bottom_edge_hugs_window_bottom():
    ox, oy = dock_origin({"edge": "b", "along": 0.5}, WIN, SCREEN_H, PW, PH, SH, MARGIN)
    _, cont_b, _, _ = _content_edges(ox, oy)
    assert abs(cont_b - (CB + MARGIN)) < 0.01


def test_dock_origin_top_edge_hugs_window_top():
    ox, oy = dock_origin({"edge": "t", "along": 0.5}, WIN, SCREEN_H, PW, PH, SH, MARGIN)
    _, _, _, cont_t = _content_edges(ox, oy)
    assert abs(cont_t - (CT - MARGIN)) < 0.01


def test_dock_origin_along_endpoints_span_the_edge():
    o0 = dock_origin({"edge": "r", "along": 0.0}, WIN, SCREEN_H, PW, PH, SH, MARGIN)
    o1 = dock_origin({"edge": "r", "along": 1.0}, WIN, SCREEN_H, PW, PH, SH, MARGIN)
    assert abs((o0[1] + PH / 2) - CB) < 0.01     # along 0 -> window bottom
    assert abs((o1[1] + PH / 2) - CT) < 0.01     # along 1 -> window top


def test_detect_dock_snaps_to_nearest_right_edge():
    windows = [(1, 0, 0, 1000, 800)]
    hud = (960, 400, 1000, 448)                  # content right ≈ window right
    d = detect_dock(hud, windows, SCREEN_H, 46)
    assert d and d["win"] == 1 and d["edge"] == "r"


def test_detect_dock_none_when_far_from_all_edges():
    windows = [(1, 0, 0, 1000, 800)]
    hud = (480, 400, 540, 448)                   # middle of the window
    assert detect_dock(hud, windows, SCREEN_H, 46) is None


def test_detect_dock_picks_the_correct_window_among_many():
    w1 = (1, 0, 0, 500, 800)                     # left window, right edge at 500
    w2 = (2, 600, 0, 500, 800)                   # right window, left edge at 600
    hud = (605, 400, 645, 448)                   # content left ≈ w2's left edge
    d = detect_dock(hud, [w1, w2], SCREEN_H, 46)
    assert d and d["win"] == 2 and d["edge"] == "l"


def test_detect_dock_along_reflects_vertical_position():
    windows = [(1, 0, 0, 1000, 800)]             # cocoa bottom=100 top=900
    # HUD near right edge, vertically centered at cocoa y=500 -> along ≈ 0.5
    hud = (960, 476, 1000, 524)                  # center y = 500
    d = detect_dock(hud, windows, SCREEN_H, 46)
    assert d and abs(d["along"] - 0.5) < 0.01
