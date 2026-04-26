#!/usr/bin/env python3
"""Render every style × theme combination to SVG for the README.

Output: docs/images/<style>-<theme>.svg

Each SVG is a self-contained snapshot — no external fonts. Renders the
exact ANSI output you'd see in your terminal but with crisp vector text.
"""

import re
import sys
from pathlib import Path
from html import escape

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from claude_statusbar.styles import RENDERERS, render
from claude_statusbar.themes import BUILTIN_THEMES

OUT = ROOT / "docs" / "images"
OUT.mkdir(parents=True, exist_ok=True)

# Snapshot data — chosen to put each segment in a different severity tier.
DATA = dict(
    msgs_pct=58, weekly_pct=24,
    reset_5h="2h47m", reset_7d="3d12h",
    model="Opus 4.7(45.0k/1.0M)",
    lang_text="", pet_text="",
    bypass=False, use_color=True,
    warning_threshold=30.0, critical_threshold=70.0,
)

# ---- ANSI → SVG ----------------------------------------------------------

ANSI_RE = re.compile(r"\033\[(?P<codes>[0-9;]*)m")

# 256-color palette for fallback (we mostly receive 24-bit RGB).
def _parse_codes(codes_str):
    """Convert SGR code string into a (fg, bg, bold) tuple updating accumulator."""
    codes = [int(c) for c in codes_str.split(";") if c != ""]
    return codes


def ansi_to_segments(text):
    """Yield (fg_rgb, bg_rgb, bold, text) tuples."""
    fg = (220, 220, 220)
    bg = None
    bold = False
    pos = 0
    for m in ANSI_RE.finditer(text):
        if m.start() > pos:
            yield (fg, bg, bold, text[pos:m.start()])
        codes = _parse_codes(m.group("codes"))
        i = 0
        while i < len(codes):
            c = codes[i]
            if c == 0:
                fg, bg, bold = (220, 220, 220), None, False
                i += 1
            elif c == 1:
                bold = True; i += 1
            elif c == 2 or c == 3:
                i += 1  # dim/italic ignored
            elif c == 38 and i + 1 < len(codes) and codes[i + 1] == 2 and i + 4 < len(codes):
                fg = (codes[i + 2], codes[i + 3], codes[i + 4]); i += 5
            elif c == 48 and i + 1 < len(codes) and codes[i + 1] == 2 and i + 4 < len(codes):
                bg = (codes[i + 2], codes[i + 3], codes[i + 4]); i += 5
            else:
                i += 1
        pos = m.end()
    if pos < len(text):
        yield (fg, bg, bold, text[pos:])


def rgb(t): return f"rgb({t[0]},{t[1]},{t[2]})" if t else "none"


def render_svg(text, *, char_w=8.4, char_h=18, padding_x=12, padding_y=10,
               bg_canvas=(28, 30, 36), title=None):
    """Convert ANSI-colored text to a self-contained SVG string.

    Width per chunk is locked via SVG `textLength` + `lengthAdjust="spacingAndGlyphs"`
    so the rendering is identical regardless of which monospace font the
    viewing browser falls back to (GitHub strips most font hints).
    """
    plain = ANSI_RE.sub("", text)
    cols = len(plain)
    width = int(padding_x * 2 + cols * char_w)
    height = padding_y * 2 + char_h + (24 if title else 0)
    title_h = 24 if title else 0

    # Use only the generic monospace family; widths are pinned via textLength.
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="monospace" font-size="14">',
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="{rgb(bg_canvas)}" rx="6"/>',
    ]

    if title:
        parts.append(
            f'<text x="{padding_x}" y="{padding_y + 14}" '
            f'fill="rgb(150,155,165)" font-size="11" letter-spacing="0.5">{escape(title)}</text>'
        )

    x = padding_x
    y = padding_y + title_h + char_h - 4  # baseline
    bg_y = padding_y + title_h
    for fg, bg, bold, chunk in ansi_to_segments(text):
        if not chunk:
            continue
        seg_w = len(chunk) * char_w
        if bg is not None:
            parts.append(
                f'<rect x="{x:.2f}" y="{bg_y}" width="{seg_w:.2f}" '
                f'height="{char_h}" fill="{rgb(bg)}"/>'
            )
        weight = ' font-weight="700"' if bold else ""
        parts.append(
            f'<text x="{x:.2f}" y="{y}" fill="{rgb(fg)}"{weight} '
            f'textLength="{seg_w:.2f}" lengthAdjust="spacingAndGlyphs" '
            f'xml:space="preserve">{escape(chunk)}</text>'
        )
        x += seg_w

    parts.append("</svg>")
    return "\n".join(parts)


def main():
    written = 0
    for style_name in RENDERERS:
        for theme in BUILTIN_THEMES:
            line = render(style_name, theme=theme, **DATA)
            title = f"cs --style {style_name} --theme {theme.name}"
            # Choose canvas bg per theme (light themes need a light canvas).
            light = theme.name in ("linen", "sakura")
            canvas = (245, 240, 232) if light else (28, 30, 36)
            svg = render_svg(line, bg_canvas=canvas, title=title)
            out = OUT / f"{style_name}-{theme.name}.svg"
            out.write_text(svg, encoding="utf-8")
            written += 1
            print(f"  {out.relative_to(ROOT)}")
    print(f"\nGenerated {written} SVG snapshots in {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
