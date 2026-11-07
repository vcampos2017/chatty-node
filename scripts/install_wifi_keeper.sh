#!/usr/bin/env bash
# Run this ON the Chatty Pi, from the repo folder:
#   bash scripts/install_wifi_keeper.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
UNIT=chatty-wifi.service

if ! command -v nmcli >/dev/null; then
  echo "nmcli not found: the WiFi keeper needs NetworkManager (Raspberry Pi OS Bookworm has it)."
  exit 1
fi

sudo cp "$REPO_DIR/deploy/systemd/$UNIT" /etc/systemd/system/$UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now $UNIT
sleep 2
sudo systemctl --no-pager status $UNIT | head -n 8
echo
sudo python3 "$REPO_DIR/scripts/wifi_keeper.py" --status
echo
echo "Done. Watch it with: journalctl -u chatty-wifi -f"
