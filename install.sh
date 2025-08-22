#!/bin/bash

# Claude Status Bar Monitor - Installation Script
# This script handles all installation scenarios

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
SCRIPT_PATH="$SCRIPT_DIR/statusbar.py"

echo -e "${BLUE}==================================${NC}"
echo -e "${BLUE}Claude Status Bar Monitor Installer${NC}"
echo -e "${BLUE}==================================${NC}\n"

# Function to print colored messages
print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

# Check if Python 3 is installed
check_python() {
    if command -v python3 &> /dev/null; then
        PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
        print_success "Python $PYTHON_VERSION found"
        return 0
    else
        print_error "Python 3 is not installed"
        echo "Please install Python 3.9 or later from https://python.org"
        exit 1
    fi
}

# Check if claude-monitor is installed and install if needed
check_claude_monitor() {
    echo -e "\n${BLUE}Checking claude-monitor installation...${NC}"
    
    # Check if any version of claude-monitor is available
    if command -v claude-monitor &> /dev/null || \
       command -v cmonitor &> /dev/null || \
       command -v ccmonitor &> /dev/null || \
       command -v ccm &> /dev/null; then
        print_success "claude-monitor is already installed"
        return 0
    fi
    
    print_warning "claude-monitor not found. Need to install it."
    echo -e "\nChoose installation method:"
    echo "1) uv (recommended - fastest and cleanest)"
    echo "2) pip (standard Python package manager)"
    echo "3) pipx (isolated environment)"
    echo "4) Skip (use fallback mode - less accurate)"
    
    read -p "Enter your choice (1-4): " choice
    
    case $choice in
        1)
            install_with_uv
            ;;
        2)
            install_with_pip
            ;;
        3)
            install_with_pipx
            ;;
        4)
            print_warning "Skipping claude-monitor installation"
            print_info "The status bar will use fallback mode (less accurate)"
            ;;
        *)
            print_error "Invalid choice"
            exit 1
            ;;
    esac
}

# Install with uv
install_with_uv() {
    print_info "Installing with uv..."
    
    # Check if uv is installed
    if ! command -v uv &> /dev/null; then
        print_info "Installing uv first..."
        
        if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || "$OSTYPE" == "win32" ]]; then
            # Windows
            powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
        else
            # macOS/Linux
            curl -LsSf https://astral.sh/uv/install.sh | sh
        fi
        
        # Add uv to current session PATH
        export PATH="$HOME/.cargo/bin:$PATH"
        
        if ! command -v uv &> /dev/null; then
            print_error "Failed to install uv"
            print_info "Please restart your terminal and run this script again"
            exit 1
        fi
    fi
    
    # Install claude-monitor with uv
    uv tool install claude-monitor
    
    if command -v claude-monitor &> /dev/null; then
        print_success "claude-monitor installed successfully with uv"
    else
        print_error "Installation failed"
        exit 1
    fi
}

# Install with pip
install_with_pip() {
    print_info "Installing with pip..."
    
    # Try to install with pip
    if pip3 install --user claude-monitor 2>/dev/null || pip3 install claude-monitor 2>/dev/null; then
        print_success "claude-monitor installed successfully with pip"
        
        # Check if ~/.local/bin is in PATH
        if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
            print_warning "~/.local/bin is not in your PATH"
            print_info "Add this line to your shell config file:"
            echo 'export PATH="$HOME/.local/bin:$PATH"'
        fi
    else
        print_error "pip installation failed"
        print_info "You might need to use: pip3 install --break-system-packages claude-monitor"
        print_info "Or better: use a virtual environment"
        exit 1
    fi
}

# Install with pipx
install_with_pipx() {
    print_info "Installing with pipx..."
    
    # Check if pipx is installed
    if ! command -v pipx &> /dev/null; then
        print_info "Installing pipx first..."
        
        if command -v apt-get &> /dev/null; then
            sudo apt-get install -y pipx
        elif command -v brew &> /dev/null; then
            brew install pipx
        else
            pip3 install --user pipx
        fi
        
        pipx ensurepath
    fi
    
    # Install claude-monitor with pipx
    pipx install claude-monitor
    
    if command -v claude-monitor &> /dev/null; then
        print_success "claude-monitor installed successfully with pipx"
    else
        print_error "Installation failed"
        exit 1
    fi
}

# Make statusbar.py executable
make_executable() {
    print_info "Making statusbar.py executable..."
    chmod +x "$SCRIPT_PATH"
    print_success "statusbar.py is now executable"
}

# Test the installation
test_installation() {
    echo -e "\n${BLUE}Testing installation...${NC}"
    
    if OUTPUT=$("$SCRIPT_PATH" 2>&1); then
        print_success "Status bar is working!"
        echo -e "\nOutput: $OUTPUT"
    else
        print_error "Status bar test failed"
        echo "Error output: $OUTPUT"
        exit 1
    fi
}

# Configure shell aliases
configure_aliases() {
    echo -e "\n${BLUE}Configure shell aliases?${NC}"
    echo "This will add convenient shortcuts to your shell configuration"
    read -p "Add aliases? (y/n): " -n 1 -r
    echo
    
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_info "Skipping alias configuration"
        return
    fi
    
    # Detect shell
    SHELL_NAME=$(basename "$SHELL")
    CONFIG_FILE=""
    
    case "$SHELL_NAME" in
        bash)
            CONFIG_FILE="$HOME/.bashrc"
            ;;
        zsh)
            CONFIG_FILE="$HOME/.zshrc"
            ;;
        fish)
            CONFIG_FILE="$HOME/.config/fish/config.fish"
            ;;
        *)
            print_warning "Unknown shell: $SHELL_NAME"
            print_info "Please manually add aliases to your shell configuration"
            return
            ;;
    esac
    
    # Alias lines to add
    ALIAS_MARKER="# Claude Status Bar Monitor aliases"
    ALIAS_LINES="
$ALIAS_MARKER
alias claude-status='$SCRIPT_PATH'
alias cs='$SCRIPT_PATH'
alias cstatus='$SCRIPT_PATH'
"
    
    # Check if aliases already exist
    if grep -q "$ALIAS_MARKER" "$CONFIG_FILE" 2>/dev/null; then
        print_info "Aliases already configured in $CONFIG_FILE"
    else
        echo "$ALIAS_LINES" >> "$CONFIG_FILE"
        print_success "Aliases added to $CONFIG_FILE"
        print_info "Run 'source $CONFIG_FILE' to use them in current session"
    fi
    
    echo -e "\n${GREEN}Available commands:${NC}"
    echo "  claude-status  - Check Claude usage"
    echo "  cs            - Short alias"
    echo "  cstatus       - Alternative alias"
}

# Integration options
show_integration_options() {
    echo -e "\n${BLUE}Integration Options${NC}"
    echo "You can integrate the status bar with:"
    echo ""
    echo "1. tmux (add to ~/.tmux.conf):"
    echo "   set -g status-right '#($SCRIPT_PATH)'"
    echo "   set -g status-interval 10"
    echo ""
    echo "2. Zsh prompt (add to ~/.zshrc):"
    echo "   claude_usage() { $SCRIPT_PATH }"
    echo "   RPROMPT='\$(claude_usage)'"
    echo ""
    echo "3. i3 status bar (add to i3 config):"
    echo "   bar {"
    echo "       status_command while :; do echo \"\$($SCRIPT_PATH)\"; sleep 10; done"
    echo "   }"
}

# Main installation flow
main() {
    # Check Python
    check_python
    
    # Check and install claude-monitor
    check_claude_monitor
    
    # Make script executable
    make_executable
    
    # Test installation
    test_installation
    
    # Configure aliases
    configure_aliases
    
    # Show integration options
    show_integration_options
    
    echo -e "\n${GREEN}==================================${NC}"
    echo -e "${GREEN}Installation Complete! 🎉${NC}"
    echo -e "${GREEN}==================================${NC}"
    echo ""
    echo "Run '$SCRIPT_PATH' or use configured aliases to check Claude usage"
    echo "For more information, see: $SCRIPT_DIR/README.md"
}

# Run main function
main