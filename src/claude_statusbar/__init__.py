"""Claude Status Bar Monitor - Lightweight token usage monitor"""

import importlib.metadata as metadata


def _get_version() -> str:
    try:
        return metadata.version("claude-statusbar")
    except metadata.PackageNotFoundError:
        return "0.0.0"


__version__ = _get_version()

from .core import main

__all__ = ["main", "__version__"]
