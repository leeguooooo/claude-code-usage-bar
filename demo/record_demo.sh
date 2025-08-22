#!/bin/bash

# Demo script for recording installation and usage of claude-statusbar
# Requires: asciinema (brew install asciinema) and asciicast2gif or svg-term-cli

echo "📹 Claude Status Bar Demo Recording Script"
echo "========================================="
echo ""
echo "This script will help you record a demo of the installation process."
echo "Prerequisites: asciinema (brew install asciinema)"
echo ""

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Start recording
echo -e "${BLUE}Starting recording...${NC}"
echo "Press Ctrl+D when done recording"
echo ""

asciinema rec --title="Claude Status Bar Installation Demo" demo.cast

echo ""
echo -e "${GREEN}Recording saved to demo.cast${NC}"
echo ""
echo "To convert to GIF, you can use:"
echo "1. Upload to asciinema.org and use their embed"
echo "2. Use svg-term-cli: npx svg-term-cli --cast demo.cast --out demo.svg"
echo "3. Use asciicast2gif: docker run --rm -v \$PWD:/data asciinema/asciicast2gif demo.cast demo.gif"
echo ""
echo "Demo script outline:"
echo "==================="
echo "1. Show current directory: pwd"
echo "2. Show we don't have claude-statusbar: which claude-statusbar (should fail)"
echo "3. Run installation: curl -fsSL https://raw.githubusercontent.com/leeguooooo/claude-code-usage-bar/main/web-install.sh | bash"
echo "4. Show it's installed: which claude-statusbar"
echo "5. Run it: claude-statusbar"
echo "6. Show the alias: cs"