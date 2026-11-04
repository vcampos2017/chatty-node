#!/usr/bin/env bash
# Run this ON the Chatty Pi, from the repo folder:
#   bash scripts/install_mqtt.sh
# Installs the Mosquitto broker (the nodes' message board) and the Python
# library Chatty uses to listen to it, then restarts Chatty.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

sudo apt-get update
sudo apt-get install -y mosquitto mosquitto-clients python3-paho-mqtt

sudo cp "$REPO_DIR/deploy/mosquitto/chatty-nodes.conf" /etc/mosquitto/conf.d/chatty-nodes.conf
sudo systemctl enable mosquitto
sudo systemctl restart mosquitto

# chatty-voice may run from a virtualenv; make sure its Python has paho too
PY="$(systemctl show -p ExecStart --value chatty-voice 2>/dev/null | sed -n 's/.*path=\([^ ;]*\).*/\1/p')"
if [ -n "$PY" ] && ! "$PY" -c "import paho.mqtt.client" 2>/dev/null; then
  echo "Installing paho-mqtt for $PY"
  if ! sudo "$PY" -m pip install paho-mqtt; then
    echo "Couldn't install paho-mqtt for $PY. Chatty will run without the node network."
  fi
fi

sudo systemctl restart chatty-voice
sleep 3
systemctl --no-pager --lines=0 status mosquitto | head -n 4
echo
echo "Broker is up. Watch the nodes check in with:"
echo "  mosquitto_sub -h localhost -t 'chatty/nodes/#' -v"
