#!/bin/bash
# setup.sh — install the JARVIS menu bar app and its launchd agents.
#
# Run once after cloning or when updating to regenerate plists.
# Safe to re-run: generate_plists.py skips files that don't need changes.
#
# Usage:
#   cd /path/to/jarvis
#   bash menubar/setup.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MENU_DIR="$REPO_ROOT/menubar"

echo "=== JARVIS menu bar setup ==="
echo "Repo: $REPO_ROOT"
echo ""

# ── 1. Install Python dependencies ───────────────────────────────────────────
echo "1. Installing Python dependencies..."
cd "$REPO_ROOT"
uv sync
echo "   Done."
echo ""

# ── 2. Optionally install Open WebUI ─────────────────────────────────────────
WEBUI_BIN="$HOME/.local/bin/open-webui"
if [[ -x "$WEBUI_BIN" ]]; then
    echo "2. Open WebUI already installed at $WEBUI_BIN — skipping."
else
    echo "2. Installing Open WebUI..."
    # open-webui depends on pyarrow which has no pre-built wheel for Python 3.14.
    # Pin to 3.12 so uv uses the available binary wheel and skips a source build.
    # cmake is required for the pyarrow source build fallback; install it first.
    if ! command -v cmake &>/dev/null; then
        echo "   cmake not found — installing via Homebrew..."
        brew install cmake
    fi
    if uv tool install open-webui --python 3.12; then
        echo "   Done."
    else
        echo "   [WARN] open-webui install failed — skipping. You can install it manually later." >&2
        echo "          The rest of setup will continue." >&2
    fi
fi
echo ""

# ── 3. Generate and install launchd plists ───────────────────────────────────
echo "3. Generating launchd plists..."
cd "$REPO_ROOT"
uv run python menubar/generate_plists.py
echo ""

# ── 4. Load the menu bar agent ───────────────────────────────────────────────
PLIST="$HOME/Library/LaunchAgents/com.jarvis.menubar.plist"
if [[ -f "$PLIST" ]]; then
    # Unload first in case a stale copy is already registered.
    launchctl unload "$PLIST" 2>/dev/null || true
    echo "4. Loading com.jarvis.menubar..."
    launchctl load -w "$PLIST"
    echo "   Done."
else
    echo "4. [WARN] $PLIST not found; re-run generate_plists.py first." >&2
fi
echo ""

echo "=== Setup complete ==="
echo "The JARVIS menu bar app is now running."
echo "Check /tmp/jarvis-menubar.err if the icon does not appear."
echo ""
echo "To install Open WebUI plist (started on-demand from the menu):"
echo "  launchctl load $HOME/Library/LaunchAgents/com.openwebui.plist"
