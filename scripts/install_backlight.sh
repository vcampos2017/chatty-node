#!/usr/bin/env bash
# Let Chatty's face dim the screen (src/backlight.py). Run once ON the Chatty Pi:
#   bash scripts/install_backlight.sh
# It lets the "video" group change the screen brightness (now and after every
# boot) and makes sure the pi user is in that group. Nothing else changes.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RULE=99-chatty-backlight.rules

if ! ls /sys/class/backlight/*/brightness >/dev/null 2>&1; then
  echo "No screen backlight found in /sys/class/backlight, so there's nothing to dim."
  exit 1
fi

sudo install -m 0644 "$REPO_DIR/deploy/udev/$RULE" "/etc/udev/rules.d/$RULE"
for B in /sys/class/backlight/*/brightness; do      # now, without a reboot
  sudo chgrp video "$B"
  sudo chmod g+w "$B"
done
if ! id -nG "${SUDO_USER:-$USER}" | grep -qw video; then
  sudo usermod -aG video "${SUDO_USER:-$USER}"
  echo "Added ${SUDO_USER:-$USER} to the video group."
fi

ls -l /sys/class/backlight/*/brightness
echo "Done. Restart the face so it picks this up:  sudo systemctl restart chatty-face"
