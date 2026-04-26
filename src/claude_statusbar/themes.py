"""Color themes for the status line.

A Theme is a pure palette — it has no opinion about layout. Layout lives in
styles.py. Any Style can render with any Theme; new themes are added by
appending to BUILTIN_THEMES.
"""

from dataclasses import dataclass
from typing import Tuple

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

    # Capsule fills — one distinct hue per metric type
    pill_5h: RGB
    pill_7d: RGB
    pill_model: RGB
    pill_lang: RGB
    pill_ink: RGB    # text color used on pill backgrounds


BUILTIN_THEMES = [
    Theme(
        name="graphite",
        description="深冷石墨 — 安静、专业、对深色终端友好",
        ink=(218, 221, 225), mute=(120, 125, 132), edge=(75, 80, 88),
        s_ok=(120, 200, 192), s_warn=(232, 178, 96), s_hot=(232, 116, 116),
        pill_5h=(38, 70, 83), pill_7d=(42, 56, 79),
        pill_model=(60, 47, 65), pill_lang=(52, 65, 47),
        pill_ink=(238, 235, 224),
    ),
    Theme(
        name="twilight",
        description="紫调暮光 — 柔和的紫/玫瑰色调，偏文艺",
        ink=(232, 225, 240), mute=(140, 130, 160), edge=(85, 75, 105),
        s_ok=(160, 210, 180), s_warn=(232, 160, 90), s_hot=(228, 100, 140),
        pill_5h=(58, 52, 90), pill_7d=(72, 46, 82),
        pill_model=(86, 52, 72), pill_lang=(50, 72, 90),
        pill_ink=(245, 238, 250),
    ),
    Theme(
        name="linen",
        description="米色亚麻 — 浅色终端 / 阳光主题专用",
        ink=(60, 55, 50), mute=(130, 120, 110), edge=(190, 180, 165),
        s_ok=(80, 140, 120), s_warn=(190, 130, 60), s_hot=(190, 80, 80),
        pill_5h=(214, 200, 178), pill_7d=(222, 210, 196),
        pill_model=(208, 196, 200), pill_lang=(202, 210, 194),
        pill_ink=(45, 40, 38),
    ),
    Theme(
        name="nord",
        description="Nord — 北欧极地蓝调，经典开发者配色",
        ink=(216, 222, 233), mute=(129, 161, 193), edge=(76, 86, 106),
        s_ok=(163, 190, 140), s_warn=(235, 203, 139), s_hot=(191, 97, 106),
        pill_5h=(46, 52, 64), pill_7d=(59, 66, 82),
        pill_model=(67, 76, 94), pill_lang=(46, 52, 64),
        pill_ink=(229, 233, 240),
    ),
    Theme(
        name="dracula",
        description="Dracula — 紫黑高对比，吸血鬼风",
        ink=(248, 248, 242), mute=(98, 114, 164), edge=(68, 71, 90),
        s_ok=(80, 250, 123), s_warn=(241, 250, 140), s_hot=(255, 85, 85),
        pill_5h=(40, 42, 54), pill_7d=(68, 71, 90),
        pill_model=(80, 50, 100), pill_lang=(50, 80, 60),
        pill_ink=(248, 248, 242),
    ),
    Theme(
        name="sakura",
        description="樱花 — 粉米暖调，可爱治愈系",
        ink=(75, 50, 60), mute=(160, 110, 130), edge=(220, 180, 195),
        s_ok=(120, 170, 130), s_warn=(220, 150, 90), s_hot=(210, 90, 110),
        pill_5h=(245, 215, 220), pill_7d=(238, 200, 215),
        pill_model=(225, 210, 230), pill_lang=(220, 230, 215),
        pill_ink=(75, 50, 60),
    ),
    Theme(
        name="mono",
        description="纯灰阶 — 极简黑白，专注阅读",
        ink=(228, 228, 228), mute=(140, 140, 140), edge=(70, 70, 70),
        s_ok=(180, 180, 180), s_warn=(220, 220, 220), s_hot=(250, 250, 250),
        pill_5h=(45, 45, 45), pill_7d=(60, 60, 60),
        pill_model=(75, 75, 75), pill_lang=(50, 50, 50),
        pill_ink=(235, 235, 235),
    ),
]

_BY_NAME = {t.name: t for t in BUILTIN_THEMES}


def get_theme(name: str) -> Theme:
    """Return theme by name, falling back to graphite if unknown."""
    return _BY_NAME.get(name, _BY_NAME["graphite"])


def list_themes() -> list[Theme]:
    return list(BUILTIN_THEMES)
