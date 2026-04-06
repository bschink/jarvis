#!/usr/bin/env zsh
# install.sh — deploy JARVIS scripts and restart live services
# Run from the repo root after editing any script or config.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET_DIR="$HOME/scripts"

# ── Scripts ───────────────────────────────────────────────────────────────────

SCRIPTS=(
    jarvis_config.py
    jarvis_log.py
    jarvis-status.py
    whisper-dictate.py
    kokoro-server.py
    tts-router.py
    tts-narrate.py
)

echo "📦 Installing scripts → $TARGET_DIR"
for s in "${SCRIPTS[@]}"; do
    cp "$REPO_DIR/scripts/$s" "$TARGET_DIR/$s"
    echo "   ✅ $s"
done

# ── Launchd plists ────────────────────────────────────────────────────────────

PLISTS=(
    com.whisper.server
    com.whisper.dictate
    com.kokoro.server
    com.tts.narrate
)

echo "\n📋 Updating LaunchAgents plists"
for svc in "${PLISTS[@]}"; do
    src="$REPO_DIR/launchd/${svc}.plist"
    dst="$HOME/Library/LaunchAgents/${svc}.plist"
    sed "s/YOURUSERNAME/$(whoami)/g" "$src" > "$dst"
    echo "   ✅ $svc"
done

# ── Restart running services ──────────────────────────────────────────────────

# whisper-server is a binary managed by Homebrew — only restart if script-driven services changed.
SERVICES=(com.whisper.dictate com.kokoro.server com.tts.narrate)

echo "\n🔄 Restarting live services"
for svc in "${SERVICES[@]}"; do
    if launchctl list 2>/dev/null | grep -q "$svc"; then
        launchctl kickstart -k "gui/$(id -u)/$svc" 2>/dev/null && echo "   🔄 $svc restarted" || echo "   ⚠️  $svc restart failed (check logs)"
    else
        echo "   ⏭  $svc not loaded — skipping"
    fi
done

echo "\n✅ Done. Tail logs with: tail -f /tmp/*.log"
