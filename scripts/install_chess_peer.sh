#!/usr/bin/env bash
# Run this ON A NODE (Lightning, Rain, Greenhouse...) to let it play its own chess
# moves when Chatty challenges it. Optional: without it Chatty moves for the node.
#
#   bash install_chess_peer.sh lightning [broker]
#
# Needs chess_peer.py and chess_engine.py in the same folder as this script
# (copy them from Chatty: see the Pi steps). Installs a tiny systemd service
# "chatty-chess" that runs at the lowest CPU priority, capped at 25% of one core.
set -euo pipefail

NAME="${1:?Usage: bash install_chess_peer.sh <node-name> [broker-host]}"
HOST="${2:-chatty-node.local}"
DIR="$(cd "$(dirname "$0")" && pwd)"
USER_NAME="$(id -un)"

for f in chess_peer.py chess_engine.py; do
  [ -f "$DIR/$f" ] || { echo "Missing $DIR/$f"; exit 1; }
done
python3 -c "import paho.mqtt.client" 2>/dev/null || sudo apt-get install -y python3-paho-mqtt

sudo tee /etc/systemd/system/chatty-chess.service >/dev/null <<EOF
[Unit]
Description=Chess player for Chatty's node network ($NAME)
After=network-online.target
Wants=network-online.target

[Service]
User=$USER_NAME
ExecStart=/usr/bin/python3 $DIR/chess_peer.py --name $NAME --host $HOST
Restart=on-failure
RestartSec=30
Nice=19
CPUQuota=25%
MemoryMax=60M

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now chatty-chess
sleep 2
systemctl --no-pager --lines=3 status chatty-chess | head -n 8
