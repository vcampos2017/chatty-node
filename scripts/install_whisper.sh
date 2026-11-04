#!/usr/bin/env bash
# Run this ON the Chatty Pi, from the repo folder:
#   bash scripts/install_whisper.sh
# Gives Chatty sharper ears: builds whisper.cpp (speech-to-text that runs entirely
# on the Pi, no cloud) and downloads its base.en model, then restarts Chatty.
# The build takes about 10-20 minutes on a Pi 4. Safe to run again.
set -euo pipefail

WHISPER_DIR="${WHISPER_DIR:-$HOME/whisper.cpp}"
WHISPER_TAG="${WHISPER_TAG:-v1.9.5}"
WHISPER_MODEL="${WHISPER_MODEL:-base.en}"

sudo apt-get update
sudo apt-get install -y build-essential cmake git

if [ ! -d "$WHISPER_DIR/.git" ]; then
  git clone --depth 1 --branch "$WHISPER_TAG" https://github.com/ggml-org/whisper.cpp "$WHISPER_DIR"
fi
cd "$WHISPER_DIR"

if [ ! -x build/bin/whisper-cli ]; then
  echo "Building whisper.cpp (grab a coffee, this takes a while)..."
  cmake -B build -DCMAKE_BUILD_TYPE=Release
  cmake --build build -j4 --config Release --target whisper-cli
fi

if [ ! -f "models/ggml-$WHISPER_MODEL.bin" ]; then
  sh ./models/download-ggml-model.sh "$WHISPER_MODEL"
fi

echo
echo "Speed test (the sample is 11 seconds of speech):"
time ./build/bin/whisper-cli -m "models/ggml-$WHISPER_MODEL.bin" -f samples/jfk.wav \
  -l en -t 4 -nt -np -bs 1 -bo 1 -ac 640
echo "(Chatty's questions are shorter, so she should be quicker than this.)"

if [ "$WHISPER_DIR" != "/home/pi/whisper.cpp" ] || [ "$WHISPER_MODEL" != "base.en" ]; then
  echo
  echo "Add these two lines to /etc/chatty/secrets.env so Chatty finds it:"
  echo "  CHATTY_WHISPER_BIN=$WHISPER_DIR/build/bin/whisper-cli"
  echo "  CHATTY_WHISPER_MODEL=$WHISPER_DIR/models/ggml-$WHISPER_MODEL.bin"
fi

sudo systemctl restart chatty-voice
sleep 5
echo
journalctl -u chatty-voice --no-pager -n 30 | grep -i whisper || true
echo "Done. Say \"Hey Chatty\", then ask her something."
