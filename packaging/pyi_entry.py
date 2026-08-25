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

It also repairs TLS before anything can use it — see ``_ensure_ca_bundle``.
"""
import sys


def _ensure_ca_bundle() -> None:
    """Point OpenSSL at a CA store that actually exists on this machine.

    PyInstaller bundles ``libssl`` but not a certificate store, and the bundled
    OpenSSL looks for one at its *build machine's* compile-time OPENSSLDIR —
    a path that doesn't exist on the user's box. Every HTTPS call from the
    frozen binary then fails certificate verification, and because each call
    site swallows network errors, the failures are silent: `cs upgrade`
    reported "up to date" forever, the `↑newver` hint never appeared, and the
    IP-risk / relay-balance probes cached nothing but `ok: false`.

    Fixed here rather than at each call site because this is the one place
    every invocation passes through — the CLI *and* the `-m` self-spawns,
    which inherit the env var we set.
    """
    import os

    if os.environ.get("SSL_CERT_FILE") or os.environ.get("SSL_CERT_DIR"):
        return  # the user (or a parent process) already chose a store

    path = None
    try:
        import certifi
        path = certifi.where()
    except Exception:
        path = None

    if not path or not os.path.exists(path):
        path = next(
            (c for c in (
                "/etc/ssl/cert.pem",                    # macOS
                "/etc/ssl/certs/ca-certificates.crt",   # Debian / Ubuntu
                "/etc/pki/tls/certs/ca-bundle.crt",     # RHEL / Fedora
                "/etc/ssl/ca-bundle.pem",               # openSUSE
            ) if os.path.exists(c)),
            None,
        )

    if path:
        os.environ["SSL_CERT_FILE"] = path


def _run() -> int:
    _ensure_ca_bundle()
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
