"""Claude Status Bar Monitor — lightweight token usage monitor.

Lazy attributes (PEP 562) for `__version__` and `main`. Both used to be
computed at import time, costing ~25ms before any work began. The
statusLine command runs many times per second on every keystroke, so
shaving import overhead is the biggest single perf win.
"""


def __getattr__(name):
    if name == "__version__":
        # importlib.metadata.version() walks dist-info directories; that's
        # slow and only needed when the user runs `cs --version`.
        import importlib.metadata as _metadata
        try:
            v = _metadata.version("claude-statusbar")
        except _metadata.PackageNotFoundError:
            v = "0.0.0"
        globals()["__version__"] = v  # cache
        return v
    if name == "main":
        # Importing core triggers re-export of progress/cache/etc. The CLI
        # subcommand router (`cs config / themes / styles / preview`)
        # returns before this import chain is needed.
        from .core import main as _main
        globals()["main"] = _main
        return _main
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["main", "__version__"]
