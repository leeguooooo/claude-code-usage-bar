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
#      binary from the latest GitHub Release (a single self-contained
#      executable — no Python needed on your machine).
#   2. Verifies the SHA-256 checksum published alongside it.
#   3. Installs it to ~/.local/bin (no sudo; everything under $HOME) and, with
#      your [y/N] consent, adds ~/.local/bin to PATH in your shell rc.
#   4. Runs `cs --setup` to wire the Claude Code statusLine + slash commands.
#   5. On macOS, if the Claude desktop app is installed, also registers the
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
FALLBACK_URL="https://raw.githubusercontent.com/${REPO}/main/web-install.sh"

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

main() {
    command -v curl >/dev/null 2>&1 || { err "curl is required."; exit 1; }

    local asset
    asset="$(detect_asset)"
    [ -n "$asset" ] || fall_back_to_pip

    local base="https://github.com/${REPO}/releases/latest/download"
    local tmp; tmp="$(mktemp -d)"
    trap 'rm -rf "$tmp"' EXIT

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
    [ -f "$tmp/cs" ] || { err "Archive did not contain a 'cs' binary."; exit 1; }

    mkdir -p "$INSTALL_DIR"
    install -m 0755 "$tmp/cs" "$INSTALL_DIR/cs"
    # Convenience aliases as symlinks so `claude-statusbar` / `cstatus` also work.
    ln -sf "$INSTALL_DIR/cs" "$INSTALL_DIR/claude-statusbar"
    ln -sf "$INSTALL_DIR/cs" "$INSTALL_DIR/cstatus"
    ok "✓ Installed cs → $INSTALL_DIR/cs"

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
    "$INSTALL_DIR/cs" --setup || warn "cs --setup reported an issue; run it manually if the bar doesn't appear."

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
