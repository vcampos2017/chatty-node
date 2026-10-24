#!/bin/bash
# Start (or restart) Chatty's face on the Pi's screen.
pkill -f "chatty_face.py" 2>/dev/null || true
nohup env DISPLAY=:0 XAUTHORITY=/home/pi/.Xauthority \
  python3 /home/pi/chatty-node/src/chatty_face.py >/tmp/chatty_face.log 2>&1 &
sleep 2
pgrep -af "chatty_face.py" || { echo "Face did not start. Log:"; tail -20 /tmp/chatty_face.log; }
