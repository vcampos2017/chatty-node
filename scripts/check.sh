#!/usr/bin/env bash
set -euo pipefail
python3 -m py_compile src/chatty_voice_node.py
python3 -m py_compile src/chatty_node.py
echo "OK: syntax clean"
