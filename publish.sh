#!/bin/bash
# Publish to PyPI script

set -e

echo "🚀 Claude Status Bar - PyPI Publisher"
echo "====================================="
echo ""

# Check if dist folder exists
if [ ! -d "dist" ]; then
    echo "❌ No dist folder found. Building package first..."
    python -m build
fi

echo "📦 Packages to upload:"
ls -la dist/*.whl dist/*.tar.gz
echo ""

# Check if API token is configured
if [ -z "$PYPI_API_TOKEN" ]; then
    echo "⚠️  PYPI_API_TOKEN environment variable not set!"
    echo ""
    echo "To set it up:"
    echo "1. Go to https://pypi.org/manage/account/token/"
    echo "2. Create a new API token"
    echo "3. Run: export PYPI_API_TOKEN='your-token-here'"
    echo ""
    echo "Or use .pypirc file method:"
    echo "Create ~/.pypirc with:"
    echo "[pypi]"
    echo "  username = __token__"
    echo "  password = your-token-here"
    echo ""
    read -p "Do you have PyPI credentials configured? (y/n): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Please configure PyPI credentials first."
        exit 1
    fi
fi

# Test upload to TestPyPI first (optional)
echo "Would you like to test on TestPyPI first? (recommended for first time)"
read -p "Upload to TestPyPI? (y/n): " -n 1 -r
echo

if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "📤 Uploading to TestPyPI..."
    python -m twine upload --repository testpypi dist/* --verbose
    echo ""
    echo "✅ Test upload successful!"
    echo "View at: https://test.pypi.org/project/claude-statusbar/"
    echo ""
    echo "Test install with:"
    echo "pip install -i https://test.pypi.org/simple/ claude-statusbar"
    echo ""
    read -p "Continue to upload to real PyPI? (y/n): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Stopped at TestPyPI."
        exit 0
    fi
fi

# Upload to PyPI
echo "📤 Uploading to PyPI..."
echo ""

if [ -n "$PYPI_API_TOKEN" ]; then
    # Use environment variable
    python -m twine upload dist/* \
        --username __token__ \
        --password "$PYPI_API_TOKEN" \
        --verbose
else
    # Use .pypirc or prompt for credentials
    python -m twine upload dist/* --verbose
fi

echo ""
echo "🎉 Successfully published to PyPI!"
echo ""
echo "📦 Install with:"
echo "  pip install claude-statusbar"
echo "  uv tool install claude-statusbar"
echo "  pipx install claude-statusbar"
echo ""
echo "🔗 View at: https://pypi.org/project/claude-statusbar/"