#!/usr/bin/env bash
# Make Chatty's face open by itself every time the Pi boots, as a systemd
# service (chatty-face) that also brings the face back if it ever crashes.
# Run this ON the Chatty Pi, from the repo folder:
#   bash scripts/install_face_autostart.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
AUTOSTART_DIR="$HOME/.config/autostart"
UNIT=chatty-face.service

# Set aside desktop autostart entries that never ran or could cover the face:
# the old Chromium kiosk on a placeholder URL, and the earlier chatty-face entry.
for OLD in "$AUTOSTART_DIR/chatty.desktop" "$AUTOSTART_DIR/chatty-face.desktop"; do
  if [ -f "$OLD" ]; then
    if [ "$(basename "$OLD")" = chatty-face.desktop ] || grep -q "YOUR-VPS-URL-HERE" "$OLD"; then
      mv "$OLD" "$OLD.old"
      echo "Set aside $OLD (now $OLD.old)"
    fi
  fi
done

# Stop a face started by hand so the service owns the screen.
pkill -f "chatty_face.py" 2>/dev/null || true

sudo cp "$REPO_DIR/deploy/systemd/$UNIT" /etc/systemd/system/$UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now $UNIT
sleep 8
sudo systemctl --no-pager status $UNIT | head -n 8
echo "Chatty's face will now open on its own after each reboot."
