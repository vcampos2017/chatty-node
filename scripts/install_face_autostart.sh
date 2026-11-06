#!/usr/bin/env bash
# Make Chatty's face open by itself every time the Pi boots to the desktop.
# Run this ON the Chatty Pi, from the repo folder (no sudo needed):
#   bash scripts/install_face_autostart.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
AUTOSTART_DIR="$HOME/.config/autostart"

chmod +x "$REPO_DIR/scripts/start_face.sh"
mkdir -p "$AUTOSTART_DIR"
cp "$REPO_DIR/deploy/autostart/chatty-face.desktop" "$AUTOSTART_DIR/chatty-face.desktop"
echo "Installed $AUTOSTART_DIR/chatty-face.desktop"
echo "Chatty's face will now open on its own after each reboot."
