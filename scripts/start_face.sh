#!/bin/bash
# Start (or restart) Chatty's face on the Pi's screen.
# Once the chatty-face service is installed (scripts/install_face_autostart.sh),
# this just restarts the service so there is never a second copy.
if systemctl is-enabled --quiet chatty-face 2>/dev/null; then
  pkill -f "chatty_face.py" 2>/dev/null || true   # any copy started by hand
  sudo systemctl restart chatty-face
  sleep 3
  pgrep -af "chatty_face.py" || { echo "Face did not start. Log:"; journalctl -u chatty-face -n 20 --no-pager; }
  exit 0
fi
pkill -f "chatty_face.py" 2>/dev/null || true
nohup env DISPLAY=:0 XAUTHORITY=/home/pi/.Xauthority \
  python3 /home/pi/chatty-node/src/chatty_face.py >/tmp/chatty_face.log 2>&1 &
sleep 2
pgrep -af "chatty_face.py" || { echo "Face did not start. Log:"; tail -20 /tmp/chatty_face.log; }
