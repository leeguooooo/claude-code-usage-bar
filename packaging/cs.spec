# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the standalone `cs` binary.

Build from the repo root:

    pip install pyinstaller
    pyinstaller packaging/cs.spec --noconfirm

Produces a single-file executable at dist/cs. Zero runtime deps means this is a
small, self-contained binary: no Python install required on the target machine.

The desktop HUD (`cs hud`) is intentionally NOT bundled — it needs PyObjC, which
is macOS-GUI-heavy and platform-specific. `cs hud` in the binary prints a hint to
install the pip extra instead.
"""
import os
from PyInstaller.utils.hooks import copy_metadata

SPEC_DIR = os.path.dirname(os.path.abspath(SPECPATH))
SRC = os.path.join(SPEC_DIR, "src")
PKG = os.path.join(SRC, "claude_statusbar")

# Bundle the non-Python package data the code reads via Path(__file__).parent,
# plus the dist metadata so `importlib.metadata.version("claude-statusbar")`
# (updater.get_current_version) resolves the real version, not the 0.0.0 fallback.
datas = [
    (os.path.join(PKG, "commands"), "claude_statusbar/commands"),
    (os.path.join(PKG, "skills"), "claude_statusbar/skills"),
]
datas += copy_metadata("claude-statusbar")

# Modules that are only referenced as strings in `[sys.executable, "-m", ...]`
# self-spawns, so PyInstaller's import graph might miss them.
hiddenimports = [
    "claude_statusbar.cli",
    "claude_statusbar.core",
    "claude_statusbar.daemon",
    "claude_statusbar.updater",
    "claude_statusbar._git_refresh",
    "claude_statusbar._balance_refresh",
    "claude_statusbar._ip_risk_refresh",
]

# The HUD (PyObjC) and the optional claude-monitor fast path are deliberately
# excluded — HUD is a pip extra; claude-monitor runs in a separate interpreter.
excludes = [
    "claude_statusbar.hud",
    "claude_statusbar.hud_data",
    "objc",
    "Quartz",
    "AppKit",
    "Cocoa",
    "Foundation",
    "PyObjCTools",
    "claude_monitor",
]

a = Analysis(
    [os.path.join(SPEC_DIR, "packaging", "pyi_entry.py")],
    pathex=[SRC],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="cs",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
