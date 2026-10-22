"""Color themes for the status line.

A Theme is a pure palette — it has no opinion about layout. Layout lives in
styles.py. Only graphite ships now (3.50.0 cut the other eight); a stale theme
name in a config falls back to it. Per-color tweaks go through color_* keys.
"""

import dataclasses
from dataclasses import dataclass
from typing import Optional, Tuple

RGB = Tuple[int, int, int]


@dataclass(frozen=True)
class Theme:
    name: str
    description: str

    # Text
    ink: RGB         # primary text (numbers, model name)
    mute: RGB        # secondary text (labels, separators, units)
    edge: RGB        # very faint dividers / outlines

    # Severity (calm / warning / critical)
    s_ok: RGB
    s_warn: RGB
    s_hot: RGB

    # Fills — pill_ink is classic's battery overlay text; the rest are kept so
    # older Theme literals keep constructing.
    pill_5h: RGB
    pill_7d: RGB
    pill_model: RGB
    pill_lang: RGB
    pill_cost: RGB   # cost pill bg — separate from pill_lang to avoid collision
    pill_ink: RGB    # text color used on pill backgrounds

    # Linked-git-worktree marker on the identity line. Its own hue on purpose:
    # "this checkout is not the main one" is a different kind of fact from
    # severity (ok/warn/hot) and must not be read as a warning. Defaults to a
    # soft violet so custom/older Theme literals keep working.
    wt: RGB = (170, 150, 220)


BUILTIN_THEMES = [
    Theme(
        name="graphite",
        description="深冷石墨 — 安静、专业、对深色终端友好",
        ink=(218, 221, 225), mute=(120, 125, 132), edge=(75, 80, 88),
        s_ok=(78, 200, 91), s_warn=(232, 178, 96), s_hot=(232, 116, 116),
        pill_5h=(38, 70, 83), pill_7d=(42, 56, 79),
        pill_model=(60, 47, 65), pill_lang=(52, 65, 47), pill_cost=(48, 56, 50),
        pill_ink=(238, 235, 224),
        wt=(168, 152, 226),
    ),
]

_BY_NAME = {t.name: t for t in BUILTIN_THEMES}


def get_theme(name: str) -> Theme:
    """Return theme by name, falling back to graphite if unknown."""
    return _BY_NAME.get(name, _BY_NAME["graphite"])


def list_themes() -> list[Theme]:
    return list(BUILTIN_THEMES)


def parse_hex_color(s: str) -> RGB:
    """Parse '#rrggbb', '#rgb', or bare 'rrggbb'/'rgb' into an RGB tuple.

    Strict — anything else raises ValueError so the config CLI surfaces a
    clear error instead of silently shipping a broken color.
    """
    s = s.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        raise ValueError(f"color must be hex like '#4ec85b', got {s!r}")
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError as e:
        raise ValueError(f"invalid hex digits in color: {s!r}") from e


def apply_color_overrides(
    theme: Theme,
    *,
    ok: Optional[RGB] = None,
    warn: Optional[RGB] = None,
    hot: Optional[RGB] = None,
    worktree: Optional[RGB] = None,
) -> Theme:
    """Return a Theme with user-overridable colors replaced where provided.

    Pure function — never mutates the input theme. Only `s_ok / s_warn /
    s_hot / wt` are overridable; ink/mute/edge/pill_* stay as the base theme
    designed them. Pass `None` for any color to leave it untouched.
    """
    overrides: dict = {}
    if ok is not None:
        overrides["s_ok"] = ok
    if warn is not None:
        overrides["s_warn"] = warn
    if hot is not None:
        overrides["s_hot"] = hot
    if worktree is not None:
        overrides["wt"] = worktree
    if not overrides:
        return theme
    return dataclasses.replace(theme, **overrides)
