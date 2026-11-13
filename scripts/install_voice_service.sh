#!/usr/bin/env bash
# Makes chatty-voice (Chatty's main service) come back by itself:
#   - after a crash, without ever giving up (Restart=always)
#   - after a freeze: her main loop sends systemd a heartbeat; 5 minutes of
#     silence and systemd restarts her (WatchdogSec=300)
#
# Run this ON the Chatty Pi, from the repo folder:
#   bash scripts/install_voice_service.sh          install / update
#   bash scripts/install_voice_service.sh --show   just print the unit she runs with now
#   bash scripts/install_voice_service.sh --undo   take the safety settings back out
#
# If chatty-voice already exists (the usual case), its unit file is NOT changed:
# the settings go in a small add-on file (a systemd "drop-in"). A copy of the
# unit as it was is kept in ~/.local/share/chatty/chatty-voice.service.before.
# On a fresh SD card (no chatty-voice yet) it installs deploy/systemd/chatty-voice.service.
# If she doesn't come back up within 60 seconds, the change is undone by itself.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
UNIT=chatty-voice.service
DROPIN_DIR=/etc/systemd/system/chatty-voice.service.d
DROPIN="$DROPIN_DIR/chatty-safety.conf"
BACKUP="$HOME/.local/share/chatty/chatty-voice.service.before"

if [ "${1:-}" = "--show" ]; then
  systemctl cat "$UNIT"
  exit 0
fi

if [ "${1:-}" = "--undo" ]; then
  sudo rm -f "$DROPIN"
  sudo systemctl daemon-reload
  sudo systemctl restart "$UNIT"
  echo "Safety settings removed; chatty-voice restarted as before."
  exit 0
fi

undo_dropin() {
  echo "She didn't come back up with the new settings: putting things back."
  sudo rm -f "$DROPIN"
  sudo systemctl daemon-reload
  sudo systemctl restart "$UNIT" || true
  echo "Undone. Please paste this into the chat:"
  echo "  journalctl -u chatty-voice -n 40 --no-pager"
  exit 1
}

if systemctl cat "$UNIT" >/dev/null 2>&1; then
  mkdir -p "$(dirname "$BACKUP")"
  systemctl cat "$UNIT" > "$BACKUP"
  echo "Kept a copy of her current unit in $BACKUP"
  sudo mkdir -p "$DROPIN_DIR"
  sudo install -m 644 "$REPO_DIR/deploy/systemd/chatty-voice.service.d/chatty-safety.conf" "$DROPIN"
  NEW_UNIT=0
else
  PY=/usr/bin/python3
  [ -x "$REPO_DIR/venv/bin/python" ] && PY="$REPO_DIR/venv/bin/python"
  TMP="$(mktemp)"
  sed -e "s|@USER@|$(id -un)|g" -e "s|@HOME@|$HOME|g" -e "s|@PYTHON@|$PY|g" \
    "$REPO_DIR/deploy/systemd/chatty-voice.service" > "$TMP"
  sudo install -m 644 "$TMP" "/etc/systemd/system/$UNIT"
  rm -f "$TMP"
  echo "Installed a new chatty-voice unit (Python: $PY)"
  NEW_UNIT=1
fi

sudo systemctl daemon-reload
sudo systemctl enable "$UNIT" >/dev/null 2>&1 || true
sudo systemctl restart "$UNIT"

echo "Waiting up to 60 seconds for her to start..."
for i in $(seq 60); do
  sleep 1
  if systemctl is-active --quiet "$UNIT"; then
    break
  fi
done
sleep 10    # still up a little later? (a crash loop would show here)
if ! systemctl is-active --quiet "$UNIT"; then
  if [ "$NEW_UNIT" = 0 ]; then
    undo_dropin
  fi
  echo "chatty-voice isn't running. Please paste:  journalctl -u chatty-voice -n 40 --no-pager"
  exit 1
fi

echo
echo "Done. chatty-voice now restarts by itself after a crash or a 5-minute freeze."
systemctl show "$UNIT" -p Restart -p WatchdogUSec -p NotifyAccess
echo
echo "One last check in about 6 minutes (her heartbeat reaching systemd): run"
echo "  systemctl show chatty-voice -p NRestarts"
echo "It should say NRestarts=0. If the number keeps going up, run:"
echo "  bash scripts/install_voice_service.sh --undo"
