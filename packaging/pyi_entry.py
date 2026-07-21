"""PyInstaller entry point for the standalone `cs` binary.

The codebase spawns background helpers by re-invoking the Python interpreter,
e.g. ``[sys.executable, "-m", "claude_statusbar._git_refresh", toplevel]`` (see
daemon.py, core.py, identity.py, ip_risk.py, updater.py). In a normal pip/uv
install ``sys.executable`` is a real Python and ``-m`` just works.

In a frozen PyInstaller binary ``sys.executable`` is *this binary*, so those
spawns would fail. Rather than rewrite every call site, this entry point makes
the binary emulate ``python -m MODULE [args...]`` when invoked that way, running
the target module's ``__main__`` block via ``runpy``. Every existing self-spawn
keeps working unchanged.

Any other invocation dispatches to the normal CLI (``claude_statusbar.cli:main``).
"""
import sys


def _run() -> int:
    argv = sys.argv

    # Emulate `python -m MODULE [args...]` for our own self-spawns.
    if len(argv) >= 3 and argv[1] == "-m":
        module = argv[2]
        rest = argv[3:]
        # Only ever route to our own package (defensive: the binary is not a
        # general-purpose interpreter, and pip/other modules aren't bundled).
        if module == "claude_statusbar" or module.startswith("claude_statusbar."):
            import runpy
            # Present argv as the module would see it under `python -m`.
            sys.argv = [module, *rest]
            runpy.run_module(module, run_name="__main__", alter_sys=True)
            return 0
        print(
            f"cs: standalone binary cannot run `-m {module}` "
            "(only bundled claude_statusbar modules are available)",
            file=sys.stderr,
        )
        return 2

    from claude_statusbar.cli import main
    return main()


if __name__ == "__main__":
    sys.exit(_run())
