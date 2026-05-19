#!/bin/bash
# claude-statusbar — one-shot installer for `curl | bash` convenience.
#
# Usage (read the script first, please):
#   curl -fsSL https://raw.githubusercontent.com/leeguooooo/claude-code-usage-bar/main/web-install.sh -o /tmp/cs-install.sh
#   less /tmp/cs-install.sh    # audit it
#   bash /tmp/cs-install.sh
#
# Or, if you trust this repo:
#   curl -fsSL https://raw.githubusercontent.com/leeguooooo/claude-code-usage-bar/main/web-install.sh | bash
#
# What this script does (full disclosure):
#   1. Detects an available Python package manager (uv, pipx, or pip) and uses it
#      to install the `claude-statusbar` PyPI package. Nothing else is installed.
#   2. Optionally writes `alias cs=...` and `alias cstatus=...` to your shell rc
#      file (~/.bashrc, ~/.zshrc, or fish config). Asks for [y/N] confirmation
#      first, reading from /dev/tty so the prompt works under `curl | bash`.
#   3. Writes a `statusLine` block into ~/.claude/settings.json (backing up any
#      existing file first) so Claude Code picks up the bar on next launch.
#   4. Runs `claude-statusbar --version` once to verify the install worked.
#
# What this script does NOT do:
#   - No `sudo`. Everything stays under $HOME.
#   - No silent install of any other package.
#   - No telemetry, no analytics, no calls to any author-controlled server.
#     The only remote endpoints touched are PyPI (or your chosen mirror) and,
#     if no package manager is found, https://astral.sh/uv/install.sh (the
#     official uv installer from Astral) — and that branch always prints a
#     warning so you can Ctrl-C.

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}╔══════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   Claude Status Bar Quick Installer  ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════╝${NC}"
echo ""

# ----------------------------------------------------------------------------
# ask_yes_no PROMPT
#
# Returns 0 on yes, 1 on no/timeout/no-tty. Reads from /dev/tty explicitly
# because under `curl | bash` the script's own stdin is the piped HTTP body,
# not the user's keyboard. If /dev/tty isn't available (e.g. inside a CI
# container) we treat that as "no" so we never silently modify shell rc files.
# ----------------------------------------------------------------------------
ask_yes_no() {
    local prompt="$1"
    local reply
    if [ ! -r /dev/tty ]; then
        echo -e "${YELLOW}(no /dev/tty available — treating as 'no')${NC}"
        return 1
    fi
    printf "%s [y/N]: " "$prompt" > /dev/tty
    read -r reply < /dev/tty || return 1
    case "$reply" in
        y|Y|yes|YES) return 0 ;;
        *)           return 1 ;;
    esac
}

# ----------------------------------------------------------------------------
# detect_package_manager
#
# Prints "uv" | "pipx" | "pip" | "none" based on what's first on PATH.
# Preference order chosen because uv > pipx > pip for isolation + speed.
# ----------------------------------------------------------------------------
detect_package_manager() {
    if command -v uv &> /dev/null; then
        echo "uv"
    elif command -v pipx &> /dev/null; then
        echo "pipx"
    elif command -v pip &> /dev/null || command -v pip3 &> /dev/null; then
        echo "pip"
    else
        echo "none"
    fi
}

# ----------------------------------------------------------------------------
# show_current_version
#
# Print the currently-installed claude-statusbar version (if any) for context
# so the user can see what they're upgrading from. Pure read; no side effects.
# ----------------------------------------------------------------------------
show_current_version() {
    if command -v claude-statusbar &> /dev/null; then
        local current_version
        current_version=$(claude-statusbar --version 2>/dev/null | grep -o '[0-9]\+\.[0-9]\+\.[0-9]\+' || echo "unknown")
        echo -e "${YELLOW}Current version: ${current_version}${NC}"
    else
        echo -e "${YELLOW}Not currently installed${NC}"
    fi
}

# ----------------------------------------------------------------------------
# install_package
#
# Calls the detected package manager to install (or upgrade) the
# `claude-statusbar` PyPI package. Only this one package is installed.
#
# Per-channel commands:
#   uv    → `uv tool install --upgrade claude-statusbar`
#   pipx  → `pipx install --force claude-statusbar`
#   pip   → `pip install --user --upgrade claude-statusbar` (+ PATH fix-up if
#           ~/.local/bin is missing from PATH; PATH fix-up writes are
#           confirmation-gated via ask_yes_no)
#   none  → installs uv from https://astral.sh/uv/install.sh, then uv branch
#           (loud warning + confirmation before the chained curl|sh).
# ----------------------------------------------------------------------------
install_package() {
    local pm
    pm=$(detect_package_manager)

    echo -e "${BLUE}Installing/upgrading claude-statusbar...${NC}"
    show_current_version

    case $pm in
        uv)
            echo "Using uv (recommended)..."
            uv tool install --upgrade claude-statusbar
            ;;
        pipx)
            echo "Using pipx..."
            pipx install --force claude-statusbar
            ;;
        pip)
            echo "Using pip..."
            if command -v pip3 &> /dev/null; then
                pip3 install --user --upgrade claude-statusbar
            else
                pip install --user --upgrade claude-statusbar
            fi

            # pip --user puts binaries under ~/.local/bin. If that's not on
            # PATH the `cs` command won't be found. Offer to append to the
            # user's rc files, but only after explicit consent — modifying
            # shell startup is a shared-system change.
            if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
                echo -e "${YELLOW}~/.local/bin is not on your PATH.${NC}"
                if ask_yes_no "Append 'export PATH=\"\$HOME/.local/bin:\$PATH\"' to ~/.bashrc and ~/.zshrc?"; then
                    echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc 2>/dev/null || true
                    echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc  2>/dev/null || true
                    export PATH="$HOME/.local/bin:$PATH"
                    echo -e "${GREEN}✅ PATH updated.${NC}"
                else
                    echo -e "${YELLOW}Skipped. You'll need to add ~/.local/bin to PATH manually.${NC}"
                    export PATH="$HOME/.local/bin:$PATH"
                fi
            fi
            ;;
        none)
            # No Python tooling at all — the only way to bootstrap without
            # `sudo` is to install uv. uv's installer is itself a curl|sh
            # script; we warn the user and ask before chaining.
            echo -e "${YELLOW}No Python package manager found.${NC}"
            echo -e "${YELLOW}This step will download and run https://astral.sh/uv/install.sh${NC}"
            echo -e "${YELLOW}(official uv installer from Astral, the maintainers of ruff).${NC}"
            if ! ask_yes_no "Proceed with installing uv?"; then
                echo -e "${RED}Aborted. Install Python + pip manually, then re-run this script.${NC}"
                exit 1
            fi

            if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || "$OSTYPE" == "win32" ]]; then
                powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
            else
                curl -LsSf https://astral.sh/uv/install.sh | sh
            fi

            # uv installs to ~/.local/bin or ~/.cargo/bin depending on platform.
            # Make both visible to this shell so the next `uv tool install` works.
            export PATH="$HOME/.local/bin:$PATH"
            export PATH="$HOME/.cargo/bin:$PATH"

            uv tool install --upgrade claude-statusbar
            ;;
    esac
}

# ----------------------------------------------------------------------------
# configure_shell
#
# Optionally adds `alias cs=...` and `alias cstatus=...` to the user's shell
# rc file. Confirmation-gated. Pure convenience — the `cs` script itself
# ships an entry point under the same name, so skipping this just means the
# user types `claude-statusbar` instead.
# ----------------------------------------------------------------------------
configure_shell() {
    echo -e "\n${BLUE}Shell aliases (optional)${NC}"

    local shell_name
    shell_name=$(basename "$SHELL")
    local config_file=""
    case "$shell_name" in
        bash) config_file="$HOME/.bashrc" ;;
        zsh)  config_file="$HOME/.zshrc"  ;;
        fish) config_file="$HOME/.config/fish/config.fish" ;;
        *)    config_file="" ;;
    esac

    if [ -z "$config_file" ] || [ ! -f "$config_file" ]; then
        echo -e "${YELLOW}No supported shell rc file found. Skipping aliases.${NC}"
        return
    fi

    if grep -q "claude-statusbar" "$config_file" 2>/dev/null; then
        echo -e "${GREEN}✅ Aliases already configured in $config_file${NC}"
        return
    fi

    echo "Would append the following lines to $config_file:"
    echo "    # Claude Status Bar Monitor"
    echo "    alias cs='claude-statusbar'"
    echo "    alias cstatus='claude-statusbar'"
    if ask_yes_no "Append?"; then
        {
            echo ""
            echo "# Claude Status Bar Monitor"
            echo "alias cs='claude-statusbar'"
            echo "alias cstatus='claude-statusbar'"
        } >> "$config_file"
        echo -e "${GREEN}✅ Aliases added to $config_file${NC}"
    else
        echo -e "${YELLOW}Skipped.${NC}"
    fi
}

# ----------------------------------------------------------------------------
# configure_claude_statusbar
#
# Writes a `statusLine` block into ~/.claude/settings.json so Claude Code
# loads the bar on next launch. If the file already exists it is backed up
# to settings.json.backup.<timestamp> first (no overwrite without backup).
#
# The settings JSON is written via a Python helper, with the binary path
# passed through an environment variable (CS_STATUSBAR_CMD) rather than
# string-interpolated into the heredoc — avoids any shell quoting issues
# if the path contains spaces or single quotes.
# ----------------------------------------------------------------------------
configure_claude_statusbar() {
    echo -e "\n${BLUE}Configuring Claude Code statusLine...${NC}"

    local claude_settings="$HOME/.claude/settings.json"

    # Prefer the canonical uv-tool binary path over ~/.local/bin symlinks so
    # auto-update via `uv tool install --upgrade` keeps pointing at the right
    # binary even if the symlink dance changes.
    local uv_tool_cmd="$HOME/.local/share/uv/tools/claude-statusbar/bin/claude-statusbar"
    local legacy_uv_tool_cmd="$HOME/.uv/tools/claude-statusbar/bin/claude-statusbar"
    local statusbar_cmd=""
    if [ -x "$uv_tool_cmd" ]; then
        statusbar_cmd="$uv_tool_cmd"
    elif [ -x "$legacy_uv_tool_cmd" ]; then
        statusbar_cmd="$legacy_uv_tool_cmd"
    else
        statusbar_cmd=$(which claude-statusbar 2>/dev/null)
    fi

    if [ -z "$statusbar_cmd" ]; then
        echo -e "${YELLOW}⚠️  claude-statusbar command not found in PATH${NC}"
        return
    fi

    mkdir -p "$HOME/.claude"

    if [ -f "$claude_settings" ]; then
        cp "$claude_settings" "$claude_settings.backup.$(date +%Y%m%d_%H%M%S)"
        echo -e "${GREEN}✅ Backed up existing settings${NC}"
    fi

    # Pass values via env vars, not via shell interpolation into the heredoc.
    # This eliminates the only potential injection surface in the script.
    export CS_SETTINGS_PATH="$claude_settings"
    export CS_STATUSBAR_CMD="$statusbar_cmd"

    if [ -f "$claude_settings" ] && [ -s "$claude_settings" ]; then
        python3 - <<'PY' || { echo -e "${YELLOW}⚠️  Failed to update settings${NC}"; return; }
import json, os
path = os.environ["CS_SETTINGS_PATH"]
cmd  = os.environ["CS_STATUSBAR_CMD"]
try:
    with open(path) as f:
        settings = json.load(f)
except Exception:
    settings = {}
settings["statusLine"] = {"type": "command", "command": cmd, "padding": 0}
with open(path, "w") as f:
    json.dump(settings, f, indent=2)
print("✅ Updated Claude Code settings")
PY
    else
        python3 - <<'PY' || { echo -e "${YELLOW}⚠️  Failed to create settings${NC}"; return; }
import json, os
path = os.environ["CS_SETTINGS_PATH"]
cmd  = os.environ["CS_STATUSBAR_CMD"]
with open(path, "w") as f:
    json.dump({"statusLine": {"type": "command", "command": cmd, "padding": 0}}, f, indent=2)
print("✅ Created Claude Code settings")
PY
    fi

    echo -e "${GREEN}✅ Claude Code statusLine configured!${NC}"
    echo -e "${YELLOW}📝 Restart Claude Code to see the bar.${NC}"
}

# ----------------------------------------------------------------------------
# test_installation
#
# Smoke-test: just verify that `claude-statusbar` is now resolvable and prints
# a version. Does not run the bar rendering itself (that needs Claude Code
# session data, which the install path doesn't have).
# ----------------------------------------------------------------------------
test_installation() {
    echo -e "\n${BLUE}Verifying install...${NC}"
    if command -v claude-statusbar &> /dev/null; then
        local new_version
        new_version=$(claude-statusbar --version 2>/dev/null | grep -o '[0-9]\+\.[0-9]\+\.[0-9]\+' || echo "unknown")
        echo -e "${GREEN}✅ Installed: claude-statusbar ${new_version}${NC}"
    else
        echo -e "${RED}❌ claude-statusbar not on PATH after install${NC}"
        echo "Check the output above; you may need to open a new shell or run:"
        echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
        exit 1
    fi
}

# ----------------------------------------------------------------------------
# show_usage
# ----------------------------------------------------------------------------
show_usage() {
    echo -e "\n${GREEN}═══════════════════════════════════════${NC}"
    echo -e "${GREEN}Install complete.${NC}"
    echo -e "${GREEN}═══════════════════════════════════════${NC}"
    echo ""
    echo "Usage:"
    echo "  claude-statusbar      # full command"
    echo "  cstatus               # short alias (if you opted in)"
    echo "  cs                    # shortest alias (if you opted in)"
    echo ""
    echo "Next steps:"
    echo "  cs doctor             # verify the wiring"
    echo "  cs preview            # try every style × theme"
    echo ""
    echo "Disable auto-update:    export CLAUDE_STATUSBAR_NO_UPDATE=1"
}

# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------
main() {
    if ! command -v python3 &> /dev/null; then
        echo -e "${RED}Python 3 is required but not installed.${NC}"
        echo "Install Python 3.9+ from https://python.org and re-run."
        exit 1
    fi

    install_package
    configure_shell
    configure_claude_statusbar
    test_installation
    show_usage
}

main "$@"
