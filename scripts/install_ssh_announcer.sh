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
# Set to 0 to stop announcing failed login attempts
CHATTY_SSH_ANNOUNCE_FAILED=1
# Phone alerts via IFTTT: risky (failed attempts + internet logins), all, or off
CHATTY_SSH_PHONE_ALERTS=risky
# IFTTT Webhooks event name
CHATTY_SSH_IFTTT_EVENT=chatty_alert
# Set to 0 to stop saying "SSH session ended"
CHATTY_SSH_ANNOUNCE_LOGOUT=1
# Failed attempts within 10 minutes before "Requesting your assistance, please"
CHATTY_SSH_HELP_AFTER=5
# At night: none (screen only) or help (still speak when asking for assistance)
CHATTY_SSH_NIGHT_SPEAK=none
# Night mode hours (shared with the rest of Chatty if set in secrets.env)
CHATTY_NIGHT_START=22
CHATTY_NIGHT_END=7
CONF
fi

sudo systemctl daemon-reload
sudo systemctl enable --now $UNIT
sleep 2
sudo systemctl --no-pager status $UNIT | head -n 12
if ! sudo grep -qs '^IFTTT_KEY=' /etc/chatty/secrets.env /home/pi/chatty_secrets.env /etc/chatty/ssh_announcer.env; then
  echo "Note: no IFTTT_KEY found, so phone alerts are off until you add one to /etc/chatty/secrets.env"
fi
echo "Done. Open a new SSH session to hear Chatty announce it."
