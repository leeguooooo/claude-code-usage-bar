#!/usr/bin/env python3
"""Floating session HUD — Claude-branded design.

Draggable, click-to-expand/minimize, anchored bottom-right of the Claude window.
5h/7d official usage (plan-usage-history) with reset countdowns.
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
BORDER  = _c("#3d3929", 0.08)
TRACK   = _c("#e8e5db")
ORANGE  = _c("#c96442")
ORANGE2 = _c("#d97757")
GREEN   = _c("#4a8a52")

SH = 22            # shadow margin around the card
PAD = 16
EXP_W = 384
EXP_H = 104        # header + usage rows
COLLAPSED_W = 190
COLLAPSED_H = 32
MARGIN = 14
SNAP_DIST = 46          # px within which a dragged edge snaps to the Claude window
DATA_EVERY = 20.0
DURATION = 0

HUD_STATE_PATH = Path.home() / ".claude" / "claude-statusbar-hud.json"
HUD_PID_PATH = Path.home() / ".claude" / "claude-statusbar-hud.pid"
state = {"expanded": False, "u": HD.Usage(), "abs": None, "snap": "br",
         "last_data": 0.0}


def load_persist():
    try:
        d = json.loads(HUD_STATE_PATH.read_text(encoding="utf-8"))
        state["abs"] = d.get("abs")
        state["snap"] = d.get("snap", "br")
        state["expanded"] = bool(d.get("expanded", False))
    except Exception:
        pass


def save_persist():
    try:
        HUD_STATE_PATH.write_text(json.dumps({
            "abs": state["abs"], "snap": state["snap"],
            "expanded": state["expanded"]}), encoding="utf-8")
    except Exception:
        pass


def refresh_data(force=False):
    if force or time.time() - state["last_data"] > DATA_EVERY:
        state["u"] = HD.snapshot()
        state["last_data"] = time.time()


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


# ---------------- content ----------------
def build_content(card):
    for v in list(card.subviews()):
        v.removeFromSuperview()
    u = state["u"]

    if not state["expanded"]:
        _build_collapsed(card, u); return
    _build_expanded(card, u)


def _build_collapsed(card, u):
    w = COLLAPSED_W
    fh = "–" if u.fh is None else f"{u.fh}"
    sd = "–" if u.sd is None else f"{u.sd}"
    base = f"5h {fh}%    ·    7d {sd}%"
    s = NSMutableAttributedString.alloc().initWithString_(base)
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
    lab = _lbl(card, NSMakeRect(14, 7, w - 28, 18), 12.5, NSFontWeightSemibold, GREY, "")
    lab.setAttributedStringValue_(s)
    d = GoldDot.alloc().initWithFrame_(NSMakeRect(w - 26, 9, 14, 14))
    d.setWantsLayer_(True); card.addSubview_(d)


def _build_expanded(card, u):
    w = EXP_W
    # ---- header ----
    logo = _round_view(card, NSMakeRect(PAD, 14, 15, 15), ORANGE, 4)
    _lbl(logo, NSMakeRect(0, 0, 15, 15), 9.5, NSFontWeightBold, BG, "C", center=True)
    _lbl(card, NSMakeRect(PAD + 22, 14, 200, 15), 11, NSFontWeightSemibold, INK_Hdr, "CLAUDE")
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
        f = win.frame()
        np = NSMakePoint(f.origin.x + dx, f.origin.y + dy)
        win.setFrameOrigin_(np)
        state["snap"] = None                          # dragging -> detach from edge
        # store the BOTTOM-RIGHT corner so expand/collapse (different widths)
        # stay right-aligned instead of drifting
        state["abs"] = [float(np.x + f.size.width), float(np.y)]
        self._down = loc

    @objc.python_method
    def _detect_snap(self):
        b = claude_bounds()
        if not b:
            return None
        _, x, y, cw, ch = b
        sh = NSScreen.screens()[0].frame().size.height
        cl, cr = x, x + cw
        cb, ct = sh - (y + ch), sh - y
        f = self.window().frame()
        hl, hb = f.origin.x + SH, f.origin.y + SH               # content edges
        hr, ht = f.origin.x + f.size.width - SH, f.origin.y + f.size.height - SH
        near_r = abs(hr - cr) < SNAP_DIST
        near_l = abs(hl - cl) < SNAP_DIST
        near_b = abs(hb - cb) < SNAP_DIST
        near_t = abs(ht - ct) < SNAP_DIST
        v = "b" if near_b else ("t" if near_t else "")
        h = "r" if near_r else ("l" if near_l else "")
        return (v + h) if (v and h) else None

    def mouseUp_(self, ev):
        if self._moved:
            snap = self._detect_snap()
            if snap:
                state["snap"] = snap; state["abs"] = None
                self.ctrl.relayout()                            # jump onto the edge
            self._down = None; save_persist(); return
        state["expanded"] = not state["expanded"]
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
        if state["expanded"]:
            return (EXP_W, EXP_H)
        return (COLLAPSED_W, COLLAPSED_H)

    def _panel_size(self):
        cw, ch = self._content_size()
        return (cw + 2 * SH, ch + 2 * SH)

    def _origin(self):
        pw, ph = self._panel_size()
        snap = state.get("snap")
        b = claude_bounds()
        if snap and b:                                # snapped to a Claude-window corner
            _, x, y, cw, ch = b
            sh = NSScreen.screens()[0].frame().size.height
            cl, cr = x, x + cw
            cb, ct = sh - (y + ch), sh - y            # cocoa bottom / top of the window
            ox = (cr - pw + SH - MARGIN) if "r" in snap else (cl - SH + MARGIN)
            oy = (cb - SH + MARGIN) if "b" in snap else (ct - ph + SH - MARGIN)
            return NSMakePoint(ox, oy)
        if state.get("abs"):                          # free-placed (bottom-right anchor)
            return NSMakePoint(state["abs"][0] - pw, state["abs"][1])
        if b:                                         # default: bottom-right of window
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
        fr = self.panel.frame()
        if (not self._placed) or state.get("snap"):   # snapped/first: align to corner
            o = self._origin(); nx, ny = o.x, o.y; self._placed = True
        else:                                # free: keep bottom-right corner fixed on resize
            nx = (fr.origin.x + fr.size.width) - pw
            ny = fr.origin.y
        self.panel.setFrame_display_animate_(NSMakeRect(nx, ny, pw, ph), True, False)
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
        sig = (state["u"].fh, state["u"].sd, state["expanded"])
        if sig != self._sig:
            self._sig = sig
            self.relayout()
        elif state.get("snap"):                       # follow the Claude window edge
            o = self._origin(); cur = self.panel.frame().origin
            if abs(cur.x - o.x) > 0.5 or abs(cur.y - o.y) > 0.5:
                self.panel.setFrameOrigin_(o)
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
        print("[hud] already running, exiting", file=sys.stderr)
        return
    load_persist()
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    refresh_data(force=True)
    print("[hud] 5h/7d:", state["u"].fh, state["u"].sd)

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
    print("[hud] running")
    app.run()


if __name__ == "__main__":
    run(sys.argv[1:])
