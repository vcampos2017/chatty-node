#!/usr/bin/env bash
# Run this ON the Chatty Pi, from the repo folder:
#   bash scripts/install_ssh_announcer.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
UNIT=chatty-ssh-announce.service

sudo cp "$REPO_DIR/deploy/systemd/$UNIT" /etc/systemd/system/$UNIT

# Optional settings file; only created if it doesn't exist yet.
if [ ! -f /etc/chatty/ssh_announcer.env ]; then
  sudo mkdir -p /etc/chatty
  sudo tee /etc/chatty/ssh_announcer.env >/dev/null <<'CONF'
# Seconds before the same user + address is announced again
CHATTY_SSH_COOLDOWN=120
# Friendly names, e.g. 100.101.102.103=Vincent's PC,192.168.1.50=laptop
CHATTY_SSH_KNOWN=
# Set to 1 to also announce failed login attempts
CHATTY_SSH_ANNOUNCE_FAILED=0
CONF
fi

sudo systemctl daemon-reload
sudo systemctl enable --now $UNIT
sleep 2
sudo systemctl --no-pager status $UNIT | head -n 12
echo "Done. Open a new SSH session to hear Chatty announce it."
