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

# Install with detected package manager
install_package() {
    local pm=$(detect_package_manager)
    
    echo -e "${BLUE}Installing claude-statusbar...${NC}"
    
    case $pm in
        uv)
            echo "Using uv (recommended)..."
            uv tool install claude-statusbar
            # Also install claude-monitor for full functionality
            uv tool install claude-monitor
            ;;
        pipx)
            echo "Using pipx..."
            pipx install claude-statusbar
            pipx install claude-monitor
            ;;
        pip)
            echo "Using pip..."
            if command -v pip3 &> /dev/null; then
                pip3 install --user claude-statusbar claude-monitor
            else
                pip install --user claude-statusbar claude-monitor
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
            
            # Install packages with uv
            uv tool install claude-statusbar
            uv tool install claude-monitor
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

# Test installation
test_installation() {
    echo -e "\n${BLUE}Testing installation...${NC}"
    
    if command -v claude-statusbar &> /dev/null; then
        OUTPUT=$(claude-statusbar 2>&1 || true)
        echo -e "${GREEN}✅ Installation successful!${NC}"
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
    
    # Test
    test_installation
    
    # Show usage
    show_usage
}

# Run installation
main "$@"