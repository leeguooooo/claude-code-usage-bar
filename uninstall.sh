#!/bin/bash

# Claude Status Bar Monitor - Uninstall Script

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}==================================${NC}"
echo -e "${BLUE}Claude Status Bar Monitor Uninstaller${NC}"
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

# Remove shell aliases
remove_aliases() {
    echo -e "\n${BLUE}Removing shell aliases...${NC}"
    
    # Detect shell config files
    CONFIG_FILES=(
        "$HOME/.bashrc"
        "$HOME/.zshrc"
        "$HOME/.config/fish/config.fish"
    )
    
    ALIAS_MARKER="# Claude Status Bar Monitor aliases"
    
    for config_file in "${CONFIG_FILES[@]}"; do
        if [[ -f "$config_file" ]] && grep -q "$ALIAS_MARKER" "$config_file"; then
            # Remove the marker line and the following 3 lines (the aliases)
            if [[ "$OSTYPE" == "darwin"* ]]; then
                # macOS
                sed -i '' "/$ALIAS_MARKER/,+3d" "$config_file"
            else
                # Linux
                sed -i "/$ALIAS_MARKER/,+3d" "$config_file"
            fi
            print_success "Removed aliases from $config_file"
        fi
    done
}

# Ask about uninstalling claude-monitor
uninstall_claude_monitor() {
    echo -e "\n${BLUE}Claude-monitor package${NC}"
    echo "The claude-monitor package may be used by other applications."
    read -p "Do you want to uninstall claude-monitor? (y/n): " -n 1 -r
    echo
    
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_info "Keeping claude-monitor installed"
        return
    fi
    
    # Try to detect how it was installed
    if command -v claude-monitor &> /dev/null; then
        CLAUDE_MON_PATH=$(which claude-monitor)
        
        if [[ "$CLAUDE_MON_PATH" == *"/.local/share/uv/tools/"* ]]; then
            print_info "Uninstalling claude-monitor (installed with uv)..."
            uv tool uninstall claude-monitor
            print_success "claude-monitor uninstalled"
        elif [[ "$CLAUDE_MON_PATH" == *"/.local/bin/"* ]]; then
            print_info "Uninstalling claude-monitor (installed with pip)..."
            pip3 uninstall -y claude-monitor
            print_success "claude-monitor uninstalled"
        elif command -v pipx &> /dev/null && pipx list | grep -q claude-monitor; then
            print_info "Uninstalling claude-monitor (installed with pipx)..."
            pipx uninstall claude-monitor
            print_success "claude-monitor uninstalled"
        else
            print_warning "Could not determine how claude-monitor was installed"
            print_info "Please uninstall it manually if needed"
        fi
    else
        print_info "claude-monitor is not installed"
    fi
}

# Main uninstall flow
main() {
    print_warning "This will remove Claude Status Bar Monitor aliases and optionally claude-monitor"
    read -p "Continue with uninstallation? (y/n): " -n 1 -r
    echo
    
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_info "Uninstallation cancelled"
        exit 0
    fi
    
    # Remove aliases
    remove_aliases
    
    # Ask about uninstalling claude-monitor
    uninstall_claude_monitor
    
    echo -e "\n${GREEN}==================================${NC}"
    echo -e "${GREEN}Uninstallation Complete${NC}"
    echo -e "${GREEN}==================================${NC}"
    echo ""
    echo "The statusbar.py script itself was not removed."
    echo "You can delete the project directory if no longer needed:"
    echo "  rm -rf $(dirname "$0")"
}

# Run main function
main