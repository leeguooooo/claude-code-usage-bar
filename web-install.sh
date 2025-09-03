#!/bin/bash
# Claude Status Bar Monitor - Web Installer
# Usage: curl -fsSL https://raw.githubusercontent.com/leeguooooo/claude-code-usage-bar/main/web-install.sh | bash

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}╔══════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   Claude Status Bar Quick Installer  ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════╝${NC}"
echo ""

# Detect package manager preference
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

# Show current version if installed
show_current_version() {
    if command -v claude-statusbar &> /dev/null; then
        local current_version=$(claude-statusbar --version 2>/dev/null | grep -o '[0-9]\+\.[0-9]\+\.[0-9]\+' || echo "unknown")
        echo -e "${YELLOW}Current version: ${current_version}${NC}"
    else
        echo -e "${YELLOW}Not currently installed${NC}"
    fi
}

# Install with detected package manager
install_package() {
    local pm=$(detect_package_manager)
    
    echo -e "${BLUE}Installing/upgrading claude-statusbar...${NC}"
    show_current_version
    
    case $pm in
        uv)
            echo "Using uv (recommended)..."
            uv tool uninstall claude-statusbar 2>/dev/null || true
            uv tool install claude-statusbar
            # Also install claude-monitor for full functionality
            uv tool install --upgrade --force claude-monitor
            ;;
        pipx)
            echo "Using pipx..."
            pipx uninstall claude-statusbar 2>/dev/null || true
            pipx install claude-statusbar
            pipx install --force claude-monitor
            pipx upgrade claude-monitor 2>/dev/null || true
            ;;
        pip)
            echo "Using pip..."
            if command -v pip3 &> /dev/null; then
                pip3 install --user --upgrade --force-reinstall claude-statusbar claude-monitor
            else
                pip install --user --upgrade --force-reinstall claude-statusbar claude-monitor
            fi
            
            # Check PATH
            if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
                echo -e "${YELLOW}Adding ~/.local/bin to PATH...${NC}"
                echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc 2>/dev/null || true
                echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc 2>/dev/null || true
                export PATH="$HOME/.local/bin:$PATH"
            fi
            ;;
        none)
            echo -e "${YELLOW}No package manager found. Installing uv first...${NC}"
            
            # Install uv
            if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || "$OSTYPE" == "win32" ]]; then
                powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
            else
                curl -LsSf https://astral.sh/uv/install.sh | sh
            fi
            
            # Add to PATH for current session
            export PATH="$HOME/.local/bin:$PATH"
            export PATH="$HOME/.cargo/bin:$PATH"
            
            # Install packages with uv
            uv tool uninstall claude-statusbar 2>/dev/null || true
            uv tool install claude-statusbar
            uv tool install --upgrade --force claude-monitor
            ;;
    esac
}

# Configure shell integration
configure_shell() {
    echo -e "\n${BLUE}Configuring shell integration...${NC}"
    
    # Detect shell
    SHELL_NAME=$(basename "$SHELL")
    CONFIG_FILE=""
    
    case "$SHELL_NAME" in
        bash) CONFIG_FILE="$HOME/.bashrc" ;;
        zsh) CONFIG_FILE="$HOME/.zshrc" ;;
        fish) CONFIG_FILE="$HOME/.config/fish/config.fish" ;;
        *) CONFIG_FILE="" ;;
    esac
    
    if [ -n "$CONFIG_FILE" ] && [ -f "$CONFIG_FILE" ]; then
        # Check if already configured
        if ! grep -q "claude-statusbar" "$CONFIG_FILE" 2>/dev/null; then
            echo "" >> "$CONFIG_FILE"
            echo "# Claude Status Bar Monitor" >> "$CONFIG_FILE"
            echo "alias cs='claude-statusbar'" >> "$CONFIG_FILE"
            echo "alias cstatus='claude-statusbar'" >> "$CONFIG_FILE"
            echo -e "${GREEN}✅ Added aliases to $CONFIG_FILE${NC}"
        else
            echo -e "${GREEN}✅ Aliases already configured${NC}"
        fi
    fi
}

# Configure Claude Code status bar
configure_claude_statusbar() {
    echo -e "\n${BLUE}Configuring Claude Code status bar...${NC}"
    
    # Claude settings file path
    CLAUDE_SETTINGS="$HOME/.claude/settings.json"
    
    # Get the installed claude-statusbar command path
    STATUSBAR_CMD=$(which claude-statusbar 2>/dev/null)
    
    if [ -z "$STATUSBAR_CMD" ]; then
        echo -e "${YELLOW}⚠️  claude-statusbar command not found in PATH${NC}"
        return
    fi
    
    # Create .claude directory if it doesn't exist
    mkdir -p "$HOME/.claude"
    
    # Backup existing settings if they exist
    if [ -f "$CLAUDE_SETTINGS" ]; then
        cp "$CLAUDE_SETTINGS" "$CLAUDE_SETTINGS.backup.$(date +%Y%m%d_%H%M%S)"
        echo -e "${GREEN}✅ Backed up existing settings${NC}"
    fi
    
    # Check if settings file exists and has content
    if [ -f "$CLAUDE_SETTINGS" ] && [ -s "$CLAUDE_SETTINGS" ]; then
        # Update existing settings using Python
        python3 -c "
import json
import sys

try:
    with open('$CLAUDE_SETTINGS', 'r') as f:
        settings = json.load(f)
except:
    settings = {}

# Add statusLine configuration - now with integrated model display
settings['statusLine'] = {
    'type': 'command',
    'command': '$STATUSBAR_CMD',
    'padding': 0
}

with open('$CLAUDE_SETTINGS', 'w') as f:
    json.dump(settings, f, indent=2)

print('✅ Updated Claude Code settings with integrated display')
" || {
            echo -e "${YELLOW}⚠️  Failed to update settings with Python${NC}"
            return
        }
    else
        # Create new settings file
        cat > "$CLAUDE_SETTINGS" << EOF
{
  "statusLine": {
    "type": "command",
    "command": "$STATUSBAR_CMD",
    "padding": 0
  }
}
EOF
        echo -e "${GREEN}✅ Created Claude Code settings${NC}"
    fi
    
    echo -e "${GREEN}✅ Claude Code status bar configured!${NC}"
    echo -e "${YELLOW}📝 Note: Status now shows integrated format: 🤖:model(Display Name)${NC}"
    echo -e "${YELLOW}📝 Note: Restart Claude Code to see the updated status bar${NC}"
}

# Test installation
test_installation() {
    echo -e "\n${BLUE}Testing installation...${NC}"
    
    if command -v claude-statusbar &> /dev/null; then
        local new_version=$(claude-statusbar --version 2>/dev/null | grep -o '[0-9]\+\.[0-9]\+\.[0-9]\+' || echo "unknown")
        OUTPUT=$(claude-statusbar 2>&1 || true)
        echo -e "${GREEN}✅ Installation successful!${NC}"
        echo -e "${GREEN}Installed version: ${new_version}${NC}"
        echo -e "\nCurrent status: $OUTPUT"
    else
        echo -e "${RED}❌ Installation failed${NC}"
        echo "Please check the error messages above"
        exit 1
    fi
}

# Show usage instructions
show_usage() {
    echo -e "\n${GREEN}═══════════════════════════════════════${NC}"
    echo -e "${GREEN}Installation Complete! 🎉${NC}"
    echo -e "${GREEN}═══════════════════════════════════════${NC}"
    echo ""
    echo "Usage:"
    echo "  claude-statusbar    # Full command"
    echo "  cstatus            # Short alias"
    echo "  cs                 # Shortest alias"
    echo ""
    echo "Integration examples:"
    echo "  tmux:  set -g status-right '#(claude-statusbar)'"
    echo "  zsh:   RPROMPT='\$(claude-statusbar)'"
    echo ""
    echo "For more options: claude-statusbar --help"
}

# Main installation flow
main() {
    # Check Python
    if ! command -v python3 &> /dev/null; then
        echo -e "${RED}Python 3 is required but not installed${NC}"
        echo "Please install Python 3.9+ from https://python.org"
        exit 1
    fi
    
    # Install package
    install_package
    
    # Configure shell
    configure_shell
    
    # Configure Claude Code status bar
    configure_claude_statusbar
    
    # Test
    test_installation
    
    # Show usage
    show_usage
}

# Run installation
main "$@"