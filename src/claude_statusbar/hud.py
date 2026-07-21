#!/usr/bin/env python3
"""Floating session HUD — Claude-branded design.

Draggable, click-to-expand/minimize, anchored bottom-right of the Claude window.
5h/7d official usage (plan-usage-history) + scrollable AgentParty channels.
Visual spec mirrors the Claude Usage Panel design (warm #faf9f5 card, orange
gradient bars, colored status dots)."""
import sys, os, time, json
from pathlib import Path
import objc
import Quartz
from AppKit import (
    NSApplication, NSPanel, NSColor, NSTextField, NSFont, NSScreen, NSView,
    NSBezierPath, NSGradient,
    NSWindowStyleMaskBorderless, NSWindowStyleMaskNonactivatingPanel,
    NSBackingStoreBuffered, NSStatusWindowLevel,
    NSMakeRect, NSMakePoint,
    NSWindowCollectionBehaviorCanJoinAllSpaces, NSWindowCollectionBehaviorStationary,
    NSWindowCollectionBehaviorFullScreenAuxiliary, NSApp,
    NSApplicationActivationPolicyAccessory, NSEvent, NSFontWeightMedium,
    NSFontWeightSemibold, NSFontWeightBold, NSFontWeightRegular,
    NSLineBreakByTruncatingTail, NSTextAlignmentRight, NSTextAlignmentCenter,
    NSMutableAttributedString, NSForegroundColorAttributeName, NSFontAttributeName,
)
from Foundation import NSTimer

from . import hud_data as HD

# ---- Claude palette ----
def _c(hexs, a=1.0):
    h = hexs.lstrip("#")
    return NSColor.colorWithSRGBRed_green_blue_alpha_(
        int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255, a)

BG      = _c("#faf9f5")
INK     = _c("#3d3929")
INK_Hdr = _c("#6f6b5c")
GREY    = _c("#83827d")
GREY2   = _c("#a6a294")
DIVIDER = _c("#3d3929", 0.08)
BORDER  = _c("#3d3929", 0.08)
TRACK   = _c("#e8e5db")
ORANGE  = _c("#c96442")
ORANGE2 = _c("#d97757")
GREEN   = _c("#4a8a52")
DOT_GREEN = _c("#5cad63")
DOT_GOLD  = _c("#e2b93b")
DOT_RED   = _c("#8f2f2a")
HOVER   = _c("#c96442", 0.06)

SH = 22            # shadow margin around the card
PAD = 16
EXP_W = 384
HEADER_H = 104     # header + usage + divider (fixed top block)
PARTY_HDR = 30     # "AGENTPARTY" label block
LIST_TOP = HEADER_H + PARTY_HDR
AGENT_ROW_H = 46
LIST_H = 172       # scrollable area height (≈3.7 rows)
EXP_H = LIST_TOP + LIST_H + 8
COLLAPSED_W = 190
COLLAPSED_H = 32
MARGIN = 14
DATA_EVERY = 20.0
DURATION = 0

HUD_STATE_PATH = Path.home() / ".claude" / "claude-statusbar-hud.json"
HUD_PID_PATH = Path.home() / ".claude" / "claude-statusbar-hud.pid"
state = {"expanded": False, "u": HD.Usage(), "channels": [], "locked": None,
         "rows": [], "scroll": 0.0, "abs": None, "last_data": 0.0}


def load_persist():
    try:
        d = json.loads(HUD_STATE_PATH.read_text(encoding="utf-8"))
        state["abs"] = d.get("abs")
        state["locked"] = d.get("locked"); state["expanded"] = bool(d.get("expanded", False))
    except Exception:
        pass


def save_persist():
    try:
        HUD_STATE_PATH.write_text(json.dumps({
            "abs": state["abs"],
            "locked": state["locked"], "expanded": state["expanded"]}), encoding="utf-8")
    except Exception:
        pass


def refresh_data(force=False):
    if force or time.time() - state["last_data"] > DATA_EVERY:
        state["u"] = HD.snapshot()
        state["channels"] = HD.all_channels(top_n=12)
        state["last_data"] = time.time()


def dot_color(age):
    return DOT_GREEN if age < 300 else (DOT_GOLD if age < 1800 else DOT_RED)


def _pick_collapsed_channel():
    chs = state["channels"]
    if not chs:
        return None
    if state["locked"]:
        for c in chs:
            if c["key"] == state["locked"]:
                return c
    return chs[0]


def _list_h():
    return LIST_H


def _max_scroll():
    return max(0.0, len(state["channels"]) * AGENT_ROW_H - _list_h())


# ---------------- custom views ----------------
class FreePanel(objc.lookUpClass("NSPanel")):
    # Don't let AppKit clamp the window onto a screen — it fights our fixed
    # position at display edges and makes the HUD jitter. Allow any position.
    def constrainFrameRect_toScreen_(self, rect, screen):
        return rect


class Flipped(objc.lookUpClass("NSView")):
    def isFlipped(self):
        return True


class GradBar(objc.lookUpClass("NSView")):
    def initWithFrame_pct_(self, frame, pct):
        self = objc.super(GradBar, self).initWithFrame_(frame)
        if self is None: return None
        self.pct = pct or 0
        return self

    def drawRect_(self, _):
        b = self.bounds(); rad = b.size.height / 2.0
        TRACK.set()
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(b, rad, rad).fill()
        frac = max(0.0, min(1.0, self.pct / 100.0))
        if frac > 0:
            w = max(b.size.height, b.size.width * frac)
            p = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSMakeRect(0, 0, w, b.size.height), rad, rad)
            NSGradient.alloc().initWithStartingColor_endingColor_(ORANGE2, ORANGE).drawInBezierPath_angle_(p, 0.0)


class GoldDot(objc.lookUpClass("NSView")):
    def drawRect_(self, _):
        b = self.bounds()
        p = NSBezierPath.bezierPathWithOvalInRect_(b)
        NSGradient.alloc().initWithStartingColor_endingColor_(_c("#f0d067"), _c("#e2b93b")).drawInBezierPath_relativeCenterPosition_(p, (-0.3, 0.4))
        _c("#3d3929", 0.12).set(); p.setLineWidth_(1.0); p.stroke()


def _lbl(parent, frame, size, weight, color, text, right=False, center=False):
    t = NSTextField.alloc().initWithFrame_(frame)
    t.setBezeled_(False); t.setEditable_(False); t.setSelectable_(False); t.setDrawsBackground_(False)
    f = NSFont.systemFontOfSize_weight_(size, weight)
    t.setFont_(f)
    t.setTextColor_(color)
    t.cell().setLineBreakMode_(NSLineBreakByTruncatingTail)
    if right: t.setAlignment_(NSTextAlignmentRight)
    if center: t.setAlignment_(NSTextAlignmentCenter)
    t.setStringValue_(text)
    parent.addSubview_(t)
    return t


def _round_view(parent, frame, color, radius):
    v = NSView.alloc().initWithFrame_(frame)
    v.setWantsLayer_(True)
    v.layer().setBackgroundColor_(color.CGColor())
    v.layer().setCornerRadius_(radius)
    parent.addSubview_(v)
    return v


def _dot(parent, frame, color):
    v = NSView.alloc().initWithFrame_(frame)
    v.setWantsLayer_(True)
    v.layer().setBackgroundColor_(color.CGColor())
    v.layer().setCornerRadius_(frame.size.height / 2)
    v.layer().setBorderWidth_(1.0)
    v.layer().setBorderColor_(_c("#3d3929", 0.12).CGColor())
    parent.addSubview_(v)
    return v


# ---------------- content ----------------
def build_content(card):
    for v in list(card.subviews()):
        v.removeFromSuperview()
    state["rows"] = []
    u = state["u"]

    if not state["expanded"]:
        _build_collapsed(card, u); return
    _build_expanded(card, u)


def _build_collapsed(card, u):
    w = COLLAPSED_W
    fh = "–" if u.fh is None else f"{u.fh}"
    sd = "–" if u.sd is None else f"{u.sd}"
    # "5h 26% · 7d 17%"   + gold dot
    s = NSMutableAttributedString.alloc().initWithString_(f"5h {fh}%    ·    7d {sd}%")
    full = s.string()
    def paint(sub, color, font):
        r = full.rangeOfString_(sub)
        if r.length:
            s.addAttribute_value_range_(NSForegroundColorAttributeName, color, r)
            s.addAttribute_value_range_(NSFontAttributeName, font, r)
    f_lbl = NSFont.systemFontOfSize_weight_(12.5, NSFontWeightSemibold)
    f_pct = NSFont.monospacedDigitSystemFontOfSize_weight_(13, NSFontWeightBold)
    s.addAttribute_value_range_(NSFontAttributeName, f_lbl, (0, len(full)))
    paint("5h", GREY, f_lbl); paint("7d", GREY, f_lbl)
    paint("·", _c("#c9c5b8"), f_lbl)
    if u.fh is not None: paint(f"{fh}%", GREEN, f_pct)
    if u.sd is not None: paint(f"{sd}%", GREEN, f_pct)
    lab = _lbl(card, NSMakeRect(14, 7, w - 44, 18), 12.5, NSFontWeightSemibold, GREY, "")
    lab.setAttributedStringValue_(s)
    d = GoldDot.alloc().initWithFrame_(NSMakeRect(w - 26, 9, 14, 14))
    d.setWantsLayer_(True); card.addSubview_(d)


def _build_expanded(card, u):
    w = EXP_W
    # ---- header ----
    logo = _round_view(card, NSMakeRect(PAD, 14, 15, 15), ORANGE, 4)
    _lbl(logo, NSMakeRect(0, 0, 15, 15), 9.5, NSFontWeightBold, BG, "C", center=True)
    _lbl(card, NSMakeRect(PAD + 22, 14, 200, 15), 11, NSFontWeightSemibold, INK_Hdr, "CLAUDE 用量")
    # minimize button (visual)
    mb = _round_view(card, NSMakeRect(w - PAD - 20, 12, 20, 20), _c("#3d3929", 0.0), 6)
    _round_view(mb, NSMakeRect(5.5, 9.2, 9, 1.6), GREY2, 0.8)
    # ---- usage rows ----
    y = 46
    for lab, pct, cd in (("5h", u.fh, u.fh_reset_s), ("7d", u.sd, u.sd_reset_s)):
        _lbl(card, NSMakeRect(PAD, y, 26, 16), 12.5, NSFontWeightSemibold, GREY, lab)
        bar = GradBar.alloc().initWithFrame_pct_(NSMakeRect(PAD + 30, y + 4, w - PAD * 2 - 30 - 44 - 52 - 20, 7), pct)
        bar.setWantsLayer_(True); card.addSubview_(bar)
        _lbl(card, NSMakeRect(w - PAD - 52 - 52, y, 44, 16), 13, NSFontWeightBold, INK,
             ("–" if pct is None else f"{pct}%"), right=True)
        _lbl(card, NSMakeRect(w - PAD - 52, y, 52, 16), 11.5, NSFontWeightRegular, GREY2,
             HD.fmt_dur(cd), right=True)
        y += 28
    # ---- divider ----
    dv = NSView.alloc().initWithFrame_(NSMakeRect(0, HEADER_H - 1, w, 1))
    dv.setWantsLayer_(True); dv.layer().setBackgroundColor_(DIVIDER.CGColor())
    card.addSubview_(dv)
    # ---- agentparty header ----
    _lbl(card, NSMakeRect(PAD, HEADER_H + 12, 200, 14), 11, NSFontWeightSemibold, INK_Hdr, "AGENTPARTY")
    # ---- scrollable list ----
    chs = state["channels"]
    if not chs:
        _lbl(card, NSMakeRect(PAD, LIST_TOP + 6, w - 2 * PAD, 15), 12, NSFontWeightRegular, GREY2, "无活跃 channel")
        return
    state["scroll"] = max(0.0, min(state["scroll"], _max_scroll()))
    clip = Flipped.alloc().initWithFrame_(NSMakeRect(0, LIST_TOP, w, LIST_H))
    clip.setWantsLayer_(True); clip.layer().setMasksToBounds_(True)
    card.addSubview_(clip)
    total = len(chs) * AGENT_ROW_H
    inner = Flipped.alloc().initWithFrame_(NSMakeRect(0, -state["scroll"], w, max(total, LIST_H)))
    clip.addSubview_(inner)
    for i, c in enumerate(chs):
        yy = i * AGENT_ROW_H
        state["rows"].append(c["key"])
        if c["key"] == state["locked"]:
            _round_view(inner, NSMakeRect(PAD - 8, yy + 3, w - 2 * (PAD - 8), AGENT_ROW_H - 6), HOVER, 8)
        _dot(inner, NSMakeRect(PAD, yy + 11, 10, 10), dot_color(c["age_s"]))
        name_w = w - PAD - 18 - PAD - 40
        _lbl(inner, NSMakeRect(PAD + 20, yy + 6, name_w, 18), 13.5, NSFontWeightSemibold, INK, c["channel"])
        if c["unread"]:
            bw = 20 + len(str(c["unread"])) * 7
            badge = _round_view(inner, NSMakeRect(w - PAD - bw, yy + 7, bw, 16), ORANGE, 8)
            _lbl(badge, NSMakeRect(0, 0, bw, 16), 10.5, NSFontWeightBold, BG, str(c["unread"]), center=True)
        prev = (c["last_preview"] or "").replace("\n", " ")
        if c["last_from"] or prev:
            m = NSMutableAttributedString.alloc().initWithString_(f"{c['last_from']}: {prev}")
            fs = full = m.string()
            fr = fs.rangeOfString_(f"{c['last_from']}:")
            fnt = NSFont.systemFontOfSize_weight_(12, NSFontWeightRegular)
            m.addAttribute_value_range_(NSFontAttributeName, fnt, (0, len(fs)))
            m.addAttribute_value_range_(NSForegroundColorAttributeName, GREY, (0, len(fs)))
            if fr.length:
                m.addAttribute_value_range_(NSForegroundColorAttributeName, GREY2, fr)
            pl = _lbl(inner, NSMakeRect(PAD + 20, yy + 24, w - PAD - 20 - PAD, 15), 12, NSFontWeightRegular, GREY, "")
            pl.setAttributedStringValue_(m)
    if _max_scroll() > 0:
        frac = LIST_H / max(total, LIST_H)
        th = max(24, LIST_H * frac)
        ty = LIST_TOP + (LIST_H - th) * (state["scroll"] / _max_scroll())
        sb = _round_view(card, NSMakeRect(w - 5, ty, 3, th), _c("#3d3929", 0.16), 1.5)


# ---------------- interaction ----------------
class HUDView(objc.lookUpClass("NSView")):
    def initWithFrame_ctrl_(self, frame, ctrl):
        self = objc.super(HUDView, self).initWithFrame_(frame)
        if self is None: return None
        self.ctrl, self._down, self._moved = ctrl, None, False
        return self

    def mouseDown_(self, ev):
        self._down = NSEvent.mouseLocation(); self._moved = False

    def mouseDragged_(self, ev):
        if self._down is None: return
        loc = NSEvent.mouseLocation()
        dx, dy = loc.x - self._down.x, loc.y - self._down.y
        if abs(dx) + abs(dy) > 3: self._moved = True
        win = self.window()
        o = win.frame().origin
        np = NSMakePoint(o.x + dx, o.y + dy)
        win.setFrameOrigin_(np)
        state["abs"] = [float(np.x), float(np.y)]     # lock to absolute screen pos
        self._down = loc

    def scrollWheel_(self, ev):
        if not state["expanded"]: return
        state["scroll"] = max(0.0, min(_max_scroll(), state["scroll"] - ev.deltaY() * 6))
        self.ctrl.relayout()

    def mouseUp_(self, ev):
        if self._moved:
            self._down = None; save_persist(); return
        if state["expanded"]:
            loc = ev.locationInWindow()
            h = self.frame().size.height
            # card is inset by SH; convert to card-flipped coords
            fy = (h - loc.y) - SH
            if LIST_TOP <= fy <= LIST_TOP + LIST_H:
                idx = int((fy - LIST_TOP + state["scroll"]) / AGENT_ROW_H)
                if 0 <= idx < len(state["rows"]):
                    key = state["rows"][idx]
                    state["locked"] = None if state["locked"] == key else key
                    self.ctrl.relayout(); self._down = None; save_persist(); return
            state["expanded"] = False
        else:
            state["expanded"] = True
        self.ctrl.relayout(); self._down = None; save_persist()


class Ctrl(objc.lookUpClass("NSObject")):
    def initWithPanel_card_(self, panel, card):
        self = objc.super(Ctrl, self).init()
        if self is None: return None
        self.panel, self.card, self.t0, self._sig = panel, card, time.time(), None
        self._miss = 0
        self._placed = False
        return self

    def _content_size(self):
        return (EXP_W, EXP_H) if state["expanded"] else (COLLAPSED_W, COLLAPSED_H)

    def _panel_size(self):
        cw, ch = self._content_size()
        return (cw + 2 * SH, ch + 2 * SH)

    def _origin(self):
        if state.get("abs"):                          # user placed it -> fixed
            return NSMakePoint(state["abs"][0], state["abs"][1])
        b = claude_bounds(); pw, ph = self._panel_size()
        if b:
            _, x, y, cw, ch = b
            sh = NSScreen.screens()[0].frame().size.height
            ox = (x + cw) - pw + SH - MARGIN
            oy = (sh - (y + ch)) - SH + MARGIN
        else:
            f = NSScreen.screens()[0].frame()
            ox = f.size.width - pw - MARGIN; oy = MARGIN
        return NSMakePoint(ox, oy)

    def reposition(self):
        self.panel.setFrameOrigin_(self._origin())

    def relayout(self):
        cw, ch = self._content_size()
        pw, ph = self._panel_size()
        cur = self.panel.frame().origin
        if not self._placed:                 # first layout: use default/persisted spot
            o = self._origin(); cur = NSMakePoint(o.x, o.y); self._placed = True
        # keep current position (user-placed); only size/content change
        self.panel.setFrame_display_animate_(NSMakeRect(cur.x, cur.y, pw, ph), True, False)
        self.card.setFrame_(NSMakeRect(SH, SH, cw, ch))
        self.card.layer().setCornerRadius_(ch / 2 if not state["expanded"] else 14.0)
        build_content(self.card)

    def tick_(self, timer):
        if DURATION and time.time() - self.t0 > DURATION:
            NSApp().terminate_(None); return
        if claude_bounds() is None:                 # tolerate transient misses
            self._miss += 1
            if self._miss > 15 and self.panel.isVisible():   # ~1.5s truly gone
                self.panel.orderOut_(None)
            return
        self._miss = 0
        if not self.panel.isVisible():
            self.panel.orderFrontRegardless()
        refresh_data()
        sig = (state["u"].fh, state["u"].sd, state["expanded"], state["locked"],
               round(state["scroll"]), tuple((c["key"], c["unread"]) for c in state["channels"]))
        if sig != self._sig:
            self._sig = sig
            self.relayout()
        # NOTE: never reposition on tick — position is owned solely by the user's
        # drag (mouseDragged). Touching it every frame fought macOS at screen
        # edges and caused jitter.


def claude_bounds():
    opts = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
    best = None
    for w in Quartz.CGWindowListCopyWindowInfo(opts, Quartz.kCGNullWindowID):
        if "Claude" not in (w.get("kCGWindowOwnerName") or "") or w.get("kCGWindowLayer") != 0:
            continue
        b = w.get("kCGWindowBounds"); area = b["Width"] * b["Height"]
        if best is None or area > best[0]:
            best = (area, b["X"], b["Y"], b["Width"], b["Height"])
    return best


def _acquire_single_instance():
    try:
        old = int(HUD_PID_PATH.read_text())
    except (FileNotFoundError, ValueError):
        old = None
    if old and old != os.getpid():
        try:
            os.kill(old, 0)
            return False              # another live instance
        except ProcessLookupError:
            pass                      # stale pid -> take over
        except PermissionError:
            return False
    try:
        HUD_PID_PATH.write_text(str(os.getpid()))
    except Exception:
        pass
    return True


def run(argv=None):
    if not _acquire_single_instance():
        print("[hud] 已有实例在运行,退出", file=sys.stderr)
        return
    load_persist()
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    refresh_data(force=True)
    print("[hud] 5h/7d:", state["u"].fh, state["u"].sd, "| channels:", len(state["channels"]))

    pw, ph = (EXP_W + 2 * SH, EXP_H + 2 * SH)
    panel = FreePanel.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(0, 0, pw, ph),
        NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel,
        NSBackingStoreBuffered, False)
    panel.setOpaque_(False); panel.setBackgroundColor_(NSColor.clearColor())
    panel.setLevel_(NSStatusWindowLevel); panel.setIgnoresMouseEvents_(False)
    panel.setBecomesKeyOnlyIfNeeded_(True); panel.setHidesOnDeactivate_(False)
    panel.setHasShadow_(False)
    panel.setCollectionBehavior_(
        NSWindowCollectionBehaviorCanJoinAllSpaces
        | NSWindowCollectionBehaviorStationary
        | NSWindowCollectionBehaviorFullScreenAuxiliary)

    hv = HUDView.alloc().initWithFrame_ctrl_(NSMakeRect(0, 0, pw, ph), None)
    # card with warm bg, rounded corners, soft warm shadow (masksToBounds False so shadow shows)
    card = Flipped.alloc().initWithFrame_(NSMakeRect(SH, SH, EXP_W, EXP_H))
    card.setWantsLayer_(True)
    lyr = card.layer()
    lyr.setBackgroundColor_(BG.CGColor())
    lyr.setCornerRadius_(14.0)
    lyr.setBorderWidth_(1.0)
    lyr.setBorderColor_(BORDER.CGColor())
    lyr.setShadowColor_(_c("#3d3929").CGColor())
    lyr.setShadowOpacity_(0.18)
    lyr.setShadowRadius_(16.0)
    lyr.setShadowOffset_((0, -5))
    hv.addSubview_(card)
    panel.setContentView_(hv)

    ctrl = Ctrl.alloc().initWithPanel_card_(panel, card); hv.ctrl = ctrl
    ctrl.relayout(); panel.orderFrontRegardless()
    NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        0.1, ctrl, "tick:", None, True)
    print("[hud] running — Claude 面板样式")
    app.run()


if __name__ == "__main__":
    run(sys.argv[1:])
