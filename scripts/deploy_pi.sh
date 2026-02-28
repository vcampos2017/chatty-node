#!/usr/bin/env bash
set -euo pipefail

SSPI_HOST="${SPI_HOST:-pi@chatty-node}"
REPO_DIR="/home/pi/chatty-node"

#!/usr/bin/env bash
set -euo pipefail

SPI_HOST="${SPI_HOST:-pi@chatty-node}"
REPO_DIR="${REPO_DIR:-/home/pi/chatty-node}"

echo "== Deploying to $SPI_HOST =="

# 1) push latest code
ssh "$SPI_HOST" "cd '$REPO_DIR' && git fetch origin"

# 2) update the branch you’re on (default: voice-fixes if it exists, else main)
ssh "$SPI_HOST" "cd '$REPO_DIR' && \
  (git rev-parse --verify voice-fixes >/dev/null 2>&1 && git checkout voice-fixes || git checkout main) && \
  git pull --ff-only"

# 3) syntax check (fast fail)
ssh "$SPI_HOST" "cd '$REPO_DIR' && python3 -m py_compile src/chatty_voice_node.py && echo '✅ Syntax OK'"

# 4) restart service
ssh "$SPI_HOST" "sudo systemctl restart chatty-voice"

# 5) show last logs
ssh "$SPI_HOST" "sudo journalctl -u chatty-voice -n 40 --no-pager -o cat"

echo "== Done =="
