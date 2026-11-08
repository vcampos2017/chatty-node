#!/usr/bin/env bash
# Chatty's remote panel: a web page on this Pi for checking on her and asking her
# things from a phone or computer (home network or Tailscale), without touching
# her face. Run this ON the Chatty Pi, from the repo folder:
#   bash scripts/install_panel.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
UNIT=chatty-panel.service
KEY=/etc/chatty/panel_key
SUDOERS=/etc/sudoers.d/chatty-panel
ME="$(id -un)"
PORT="${CHATTY_PANEL_PORT:-8080}"

# The passcode file: belongs to this user, nobody else can read it.
sudo mkdir -p /etc/chatty
NEW_CODE=0
if [ ! -s "$KEY" ]; then
  sudo install -m 600 -o "$ME" -g "$ME" /dev/null "$KEY"
  NEW_CODE=1
else
  sudo chown "$ME:$ME" "$KEY"
  sudo chmod 600 "$KEY"
fi

# Let the panel restart her voice and face (and nothing else) without a password.
TMP="$(mktemp)"
cat > "$TMP" <<RULE
# Chatty's remote panel may restart her voice and face services, nothing else.
$ME ALL=(root) NOPASSWD: /usr/bin/systemctl restart chatty-voice, /usr/bin/systemctl restart chatty-face
RULE
if sudo visudo -cf "$TMP" >/dev/null; then
  sudo install -m 440 -o root -g root "$TMP" "$SUDOERS"
else
  echo "Skipped the restart permission (sudoers check failed)."
fi
rm -f "$TMP"

if [ "$NEW_CODE" = 1 ]; then
  python3 "$REPO_DIR/src/panel.py" --new-passcode
fi

if ss -ltn 2>/dev/null | grep -q ":$PORT " && ! systemctl is-active --quiet $UNIT; then
  echo "Port $PORT is already in use. Pick another with CHATTY_PANEL_PORT=... in /etc/chatty/secrets.env"
fi

sudo cp "$REPO_DIR/deploy/systemd/$UNIT" /etc/systemd/system/$UNIT
sudo systemctl daemon-reload
sudo systemctl enable $UNIT
sudo systemctl restart $UNIT
sleep 2
sudo systemctl --no-pager status $UNIT | head -n 6
echo
TS_IP="$(tailscale ip -4 2>/dev/null | head -n1 || true)"
LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo "Chatty's panel is open:"
[ -n "$TS_IP" ] && echo "  over Tailscale:  http://$(hostname):$PORT   (or http://$TS_IP:$PORT)"
[ -n "$LAN_IP" ] && echo "  at home:         http://$LAN_IP:$PORT"
echo "New passcode any time: python3 src/panel.py --new-passcode"
