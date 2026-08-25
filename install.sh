#!/usr/bin/env bash
# claude-statusbar — standalone binary installer (no Python, no pip required).
#
# Usage (read the script first, please):
#   curl -fsSL https://raw.githubusercontent.com/leeguooooo/claude-code-usage-bar/main/install.sh -o /tmp/cs.sh
#   less /tmp/cs.sh        # audit it
#   bash /tmp/cs.sh
#
# Or, if you trust this repo:
#   curl -fsSL https://raw.githubusercontent.com/leeguooooo/claude-code-usage-bar/main/install.sh | bash
#
# What it does (full disclosure):
#   1. Detects your OS + CPU arch and downloads the matching prebuilt `cs`
#      bundle from the latest GitHub Release (self-contained — no Python
#      needed on your machine). The installed bundle uses PyInstaller onedir,
#      not onefile, so the once-per-second status render never extracts `_MEI*`
#      runtime copies into your temp directory.
#   2. Verifies the SHA-256 checksum published alongside it.
#   3. Installs it to ~/.local/bin (no sudo; everything under $HOME) and, with
#      your [y/N] consent, adds ~/.local/bin to PATH in your shell rc.
#   4. Runs `cs --setup` to wire the Claude Code statusLine + slash commands.
#   5. Removes inactive `_MEI*` directories leaked by legacy onefile versions,
#      after stopping the old daemon and verifying no process has them open.
#   6. On macOS, if the Claude desktop app is installed, also registers the
#      floating desktop HUD to auto-start on login (`cs hud install`) — the
#      macOS binary bundles the HUD, so this needs no Python. One command wires
#      up both the terminal statusLine and the desktop panel.
#
#   If no prebuilt binary matches your platform (e.g. Linux arm64, Windows), it
#   automatically falls back to the pip/uv-based installer (web-install.sh),
#   which needs Python 3.9+.
#
# No sudo. No telemetry. The only remote hosts touched are github.com (release
# assets) and, only on fallback, PyPI / astral.sh (uv).

set -euo pipefail

REPO="leeguooooo/claude-code-usage-bar"
INSTALL_DIR="${CS_INSTALL_DIR:-$HOME/.local/bin}"
BUNDLE_ROOT="${CS_BUNDLE_ROOT:-$HOME/.local/lib/claude-statusbar}"
FALLBACK_URL="https://raw.githubusercontent.com/${REPO}/main/web-install.sh"

# A pip/uv/pipx copy of claude-statusbar competes with this binary for the one
# `cs` on PATH: whichever upgrades last rewrites the symlink and silently takes
# over. We don't remove another package manager's package behind the user's
# back, but staying quiet about it is how a stale uv 3.32.0 replaced a working
# binary install without anyone noticing.
warn_about_duplicate_installs() {
    local found=""
    [ -d "$HOME/.local/share/uv/tools/claude-statusbar" ] && found="uv tool"
    [ -d "$HOME/.local/pipx/venvs/claude-statusbar" ] && found="${found:+$found and }pipx"
    [ -n "$found" ] || return 0
    warn "Another claude-statusbar install ($found) is also present."
    echo "     Both compete for $INSTALL_DIR/cs — whichever upgrades last wins."
    echo "     Remove the other one so upgrades stay predictable:"
    [ -d "$HOME/.local/share/uv/tools/claude-statusbar" ] && \
        echo "       uv tool uninstall claude-statusbar"
    [ -d "$HOME/.local/pipx/venvs/claude-statusbar" ] && \
        echo "       pipx uninstall claude-statusbar"
}

# Scratch dir for the downloaded tarball, cleaned up on any exit. Declared here
# (not inside the function that fills it) so the trap can still see it — see the
# note at the mktemp call.
TMP_DIR=""
INSTALL_STAGE=""
INSTALLED_BUNDLE_DIR=""
cleanup() {
    [ -n "${TMP_DIR:-}" ] && rm -rf "$TMP_DIR"
    [ -n "${INSTALL_STAGE:-}" ] && rm -rf "$INSTALL_STAGE"
    return 0
}
trap cleanup EXIT

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; RED='\033[0;31m'; NC='\033[0m'

say()  { echo -e "${BLUE}$*${NC}"; }
ok()   { echo -e "${GREEN}$*${NC}"; }
warn() { echo -e "${YELLOW}$*${NC}"; }
err()  { echo -e "${RED}$*${NC}" >&2; }

echo -e "${BLUE}╔══════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   Claude Status Bar — binary install ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════╝${NC}"
echo ""

# ---------------------------------------------------------------------------
# ask_yes_no PROMPT — reads from /dev/tty so it works under `curl | bash`.
# Returns 0 on yes; anything else (incl. no tty) is treated as "no".
# ---------------------------------------------------------------------------
ask_yes_no() {
    local reply
    if [ ! -r /dev/tty ]; then
        warn "(no /dev/tty — treating as 'no')"
        return 1
    fi
    printf "%s [y/N]: " "$1" > /dev/tty
    read -r reply < /dev/tty || return 1
    case "$reply" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

# ---------------------------------------------------------------------------
# fall_back_to_pip — hand off to the Python/pip installer for platforms with no
# prebuilt binary. Runs it in-place via the same shell.
# ---------------------------------------------------------------------------
fall_back_to_pip() {
    warn "No prebuilt binary for this platform — falling back to the pip installer."
    warn "(needs Python 3.9+; it will use uv/pipx/pip, bootstrapping uv if needed)"
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$FALLBACK_URL" | bash
    else
        err "curl not found; install Python + run: pip install claude-statusbar && cs --setup"
        exit 1
    fi
    exit $?
}

# ---------------------------------------------------------------------------
# detect_asset — echo the release asset name for this OS/arch, or "" if none.
# ---------------------------------------------------------------------------
detect_asset() {
    local os arch
    case "$(uname -s)" in
        Darwin) os="darwin" ;;
        Linux)  os="linux"  ;;
        *)      echo ""; return ;;
    esac
    case "$(uname -m)" in
        arm64|aarch64) arch="arm64" ;;
        x86_64|amd64)  arch="x86_64" ;;
        *)             echo ""; return ;;
    esac
    # Published matrix: darwin arm64, linux x86_64. Everything else (Intel mac,
    # linux arm64, Windows) has no prebuilt binary → fall back to pip.
    case "$os-$arch" in
        darwin-arm64|linux-x86_64) echo "cs-${os}-${arch}.tar.gz" ;;
        *)                         echo "" ;;
    esac
}

# ---------------------------------------------------------------------------
# sha256_of FILE — portable SHA-256 (shasum on macOS, sha256sum on Linux).
# ---------------------------------------------------------------------------
sha256_of() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    else
        shasum -a 256 "$1" | awk '{print $1}'
    fi
}

# ---------------------------------------------------------------------------
# stop_old_daemon — stop the legacy onefile daemon before replacing the
# launcher. Its `_MEI*` directory can be hours old while still in active use,
# so age alone is never a safe cleanup criterion.
# ---------------------------------------------------------------------------
stop_old_daemon() {
    if [ -x "$INSTALL_DIR/cs" ]; then
        "$INSTALL_DIR/cs" daemon stop >/dev/null 2>&1 || true
        # The HUD is another long-lived frozen process. Stop it before old
        # onedir versions are pruned; the installer restarts it below when the
        # Claude desktop app is present.
        "$INSTALL_DIR/cs" hud stop >/dev/null 2>&1 || true
    fi
}

# BSD mv follows a destination symlink to a directory unless `-h` is passed;
# GNU mv uses `-T` for the same no-follow replacement semantics.
replace_path_atomically() {
    local source="$1" target="$2"
    if [ "$(uname -s)" = "Darwin" ]; then
        mv -fh "$source" "$target"
    else
        mv -fT "$source" "$target"
    fi
}

# ---------------------------------------------------------------------------
# install_onedir_bundle SOURCE_DIR — copy a release bundle into a content-
# addressed version directory and atomically repoint ~/.local/bin/cs through a
# stable `current` symlink. A failed copy can never leave a half-written CLI.
# Sets INSTALLED_BUNDLE_DIR to the final bundle directory.
# ---------------------------------------------------------------------------
install_onedir_bundle() {
    local source_dir="$1"
    mkdir -p "$INSTALL_DIR" "$BUNDLE_ROOT"

    INSTALL_STAGE="$(mktemp -d "$BUNDLE_ROOT/.install.XXXXXX")"
    cp -R "$source_dir/." "$INSTALL_STAGE/"
    chmod 0755 "$INSTALL_STAGE/cs"

    local version_line version build_id final_dir next_link
    version_line="$("$INSTALL_STAGE/cs" --version)"
    version="${version_line##* }"
    case "$version" in
        ''|*[!A-Za-z0-9._-]*) err "Invalid cs version in release bundle: $version_line"; exit 1 ;;
    esac
    build_id="$(sha256_of "$INSTALL_STAGE/cs" | cut -c1-12)"
    final_dir="$BUNDLE_ROOT/v${version}-${build_id}"

    if [ -d "$final_dir" ]; then
        rm -rf "$INSTALL_STAGE"
    else
        mv "$INSTALL_STAGE" "$final_dir"
    fi
    INSTALL_STAGE=""

    stop_old_daemon

    # `current` must remain a symlink owned by this installer. Refuse to move a
    # real directory out of the way: it may contain user data from a custom
    # CS_BUNDLE_ROOT.
    if [ -e "$BUNDLE_ROOT/current" ] && [ ! -L "$BUNDLE_ROOT/current" ]; then
        err "$BUNDLE_ROOT/current exists and is not a symlink; refusing to replace it."
        exit 1
    fi
    next_link="$BUNDLE_ROOT/.current.$$"
    ln -s "$final_dir" "$next_link"
    replace_path_atomically "$next_link" "$BUNDLE_ROOT/current"

    # Atomic rename replaces either a previous symlink or the legacy regular
    # binary without ever exposing a missing `cs` path to Claude Code.
    next_link="$INSTALL_DIR/.cs.$$"
    ln -s "$BUNDLE_ROOT/current/cs" "$next_link"
    replace_path_atomically "$next_link" "$INSTALL_DIR/cs"
    ln -sfn "$INSTALL_DIR/cs" "$INSTALL_DIR/claude-statusbar"
    ln -sfn "$INSTALL_DIR/cs" "$INSTALL_DIR/cstatus"

    INSTALLED_BUNDLE_DIR="$final_dir"
}

# ---------------------------------------------------------------------------
# prune_old_bundles KEEP_DIR — the new daemon is already running before this
# executes, so no process needs a previous onedir version.
# ---------------------------------------------------------------------------
prune_old_bundles() {
    local keep_dir="$1" old
    for old in "$BUNDLE_ROOT"/v*; do
        [ -e "$old" ] || continue
        [ "$old" = "$keep_dir" ] && continue
        [ -d "$old" ] && [ ! -L "$old" ] && rm -rf "$old"
    done
}

main() {
    command -v curl >/dev/null 2>&1 || { err "curl is required."; exit 1; }

    local asset
    asset="$(detect_asset)"
    [ -n "$asset" ] || fall_back_to_pip

    # Override is used by the offline installer integration test. Normal users
    # always take the GitHub Release URL.
    local base="${CS_RELEASE_BASE_URL:-https://github.com/${REPO}/releases/latest/download}"
    # NOTE: the scratch dir must be a global, not a `local`. The EXIT trap runs
    # after this function has already returned, so a local `tmp` is out of scope
    # by then — under `set -u` that ended the install with a bare
    # "tmp: unbound variable", and the temp dir was never cleaned up.
    TMP_DIR="$(mktemp -d)"
    local tmp="$TMP_DIR"

    say "Downloading $asset from the latest release..."
    if ! curl -fsSL "$base/$asset" -o "$tmp/$asset"; then
        warn "Download failed (no release asset yet?)."
        fall_back_to_pip
    fi

    # Verify checksum if the .sha256 sidecar is present.
    if curl -fsSL "$base/$asset.sha256" -o "$tmp/$asset.sha256" 2>/dev/null; then
        local want got
        want="$(awk '{print $1}' "$tmp/$asset.sha256")"
        got="$(sha256_of "$tmp/$asset")"
        if [ "$want" != "$got" ]; then
            err "Checksum mismatch! expected $want, got $got. Aborting."
            exit 1
        fi
        ok "✓ Checksum verified"
    else
        warn "No .sha256 published for $asset — skipping checksum verification."
    fi

    say "Extracting..."
    tar -xzf "$tmp/$asset" -C "$tmp"
    local install_mode bundle_dir
    if [ -x "$tmp/cs/cs" ]; then
        install_mode="onedir"
        install_onedir_bundle "$tmp/cs"
        bundle_dir="$INSTALLED_BUNDLE_DIR"
        ok "✓ Installed cs bundle → $bundle_dir"
        ok "✓ Linked cs → $INSTALL_DIR/cs"
        warn_about_duplicate_installs
    elif [ -f "$tmp/cs" ]; then
        # Transition compatibility: `main/install.sh` can be newer than the
        # latest Release for a short window while CI is still building the
        # first onedir asset. Keep old releases installable, but do not pretend
        # they have fixed the onefile extraction problem.
        install_mode="legacy-onefile"
        bundle_dir=""
        stop_old_daemon
        mkdir -p "$INSTALL_DIR"
        rm -f "$INSTALL_DIR/cs"
        install -m 0755 "$tmp/cs" "$INSTALL_DIR/cs"
        ln -sfn "$INSTALL_DIR/cs" "$INSTALL_DIR/claude-statusbar"
        ln -sfn "$INSTALL_DIR/cs" "$INSTALL_DIR/cstatus"
        warn "Installed a legacy onefile asset; update again after the new onedir Release finishes building."
    else
        err "Archive did not contain a 'cs' bundle."
        exit 1
    fi

    # Ensure the install dir is on PATH.
    if ! command -v cs >/dev/null 2>&1 || [ "$(command -v cs)" != "$INSTALL_DIR/cs" ]; then
        if [[ ":$PATH:" != *":$INSTALL_DIR:"* ]]; then
            warn "$INSTALL_DIR is not on your PATH."
            if ask_yes_no "Append 'export PATH=\"$INSTALL_DIR:\$PATH\"' to ~/.bashrc and ~/.zshrc?"; then
                for rc in "$HOME/.bashrc" "$HOME/.zshrc"; do
                    echo "export PATH=\"$INSTALL_DIR:\$PATH\"" >> "$rc" 2>/dev/null || true
                done
                ok "✓ PATH updated (open a new shell, or run: export PATH=\"$INSTALL_DIR:\$PATH\")"
            else
                warn "Skipped. Add $INSTALL_DIR to your PATH manually to use 'cs'."
            fi
        fi
    fi
    export PATH="$INSTALL_DIR:$PATH"

    say "Wiring Claude Code statusLine (cs --setup)..."
    local setup_ok=1
    if ! "$INSTALL_DIR/cs" --setup; then
        setup_ok=0
        warn "cs --setup reported an issue; run it manually if the bar doesn't appear."
    fi

    if [ "$install_mode" = "onedir" ]; then
        # The new process is onedir, so this scan cannot create another `_MEI`.
        # cleanup.py refuses to delete unless lsof proves the legacy directory
        # inactive; if that proof is unavailable, it leaves everything alone.
        "$INSTALL_DIR/cs" -m claude_statusbar.cleanup || true
        [ "$setup_ok" -eq 1 ] && prune_old_bundles "$bundle_dir"
    fi

    # macOS: if the Claude *desktop* app is installed, wire the floating HUD too,
    # so a single install covers BOTH surfaces — the terminal statusLine and the
    # desktop panel — with no extra steps. The macOS binary bundles the HUD, so
    # this needs no Python/pip and rides the same auto-update.
    if [ "$(uname -s)" = "Darwin" ] && \
       { [ -d "/Applications/Claude.app" ] || [ -d "$HOME/Applications/Claude.app" ]; }; then
        say "Detected the Claude desktop app — installing the floating HUD..."
        # curl-installed binaries carry no com.apple.quarantine attribute, but
        # strip it defensively so Gatekeeper never blocks the HUD's window.
        xattr -dr com.apple.quarantine "$INSTALL_DIR/cs" 2>/dev/null || true
        if "$INSTALL_DIR/cs" hud install; then
            ok "✓ Desktop HUD installed — auto-starts on login (drag to place, click to expand)"
        else
            warn "HUD setup hit an issue; run 'cs hud install' to retry."
        fi
    fi

    echo ""
    ok "═══════════════════════════════════════"
    ok "Install complete — restart Claude Code."
    ok "═══════════════════════════════════════"
    echo "  cs doctor    # verify the wiring"
    echo "  cs preview   # try every style × theme"
    echo ""
    echo "Update later:   curl -fsSL https://raw.githubusercontent.com/${REPO}/main/install.sh | bash"
    echo "Desktop HUD:    auto-installed above if the Claude desktop app was found (macOS)."
    echo "                otherwise: cs hud install"
}

main "$@"
