#!/bin/bash
# One-command installer for Blackjack Roguelite
# Usage: curl -sL https://raw.githubusercontent.com/brightblackassociates/blackjack-roguelite/main/install.sh | bash

set -e

REPO_ZIP="https://github.com/brightblackassociates/blackjack-roguelite/archive/refs/heads/main.zip"
INSTALL_DIR="$HOME/.blackjack-roguelite"
BIN_LINK="/usr/local/bin/blackjack"

# Check for python3
if ! command -v python3 &>/dev/null; then
    echo ""
    echo "  Python 3 is required but not found."
    echo "  Install it: https://www.python.org/downloads/"
    echo ""
    exit 1
fi

echo ""
echo "  Downloading Blackjack Roguelite..."

# Download and extract
TMP=$(mktemp -d)
trap "rm -rf $TMP" EXIT
curl -sL "$REPO_ZIP" -o "$TMP/game.zip"
unzip -qo "$TMP/game.zip" -d "$TMP"

# Install to home directory (overwrite previous install)
rm -rf "$INSTALL_DIR"
mv "$TMP/blackjack-roguelite-main" "$INSTALL_DIR"

# Create launcher script
cat > "$INSTALL_DIR/blackjack" << 'LAUNCHER'
#!/bin/bash
cd "$HOME/.blackjack-roguelite"
exec python3 -m blackjack_roguelite.play "$@"
LAUNCHER
chmod +x "$INSTALL_DIR/blackjack"

# Symlink into PATH if possible
if [ -d "/usr/local/bin" ] && [ -w "/usr/local/bin" ]; then
    ln -sf "$INSTALL_DIR/blackjack" "$BIN_LINK"
    CMD="blackjack"
else
    CMD="~/.blackjack-roguelite/blackjack"
fi

echo "  Done! To play, type:"
echo ""
echo "    $CMD"
echo ""
