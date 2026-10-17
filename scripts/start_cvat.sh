#!/usr/bin/env bash
# Start CVAT with Nuclio (needed for AI tools) in the background.
# Usage: ./scripts/start_cvat.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR/cvat"

sudo docker compose \
  -f docker-compose.yml \
  -f docker-compose.dev.yml \
  -f components/serverless/docker-compose.serverless.yml \
  up -d --build

# Restart AI model containers stopped by stop_cvat.sh (deployed with nuctl, not compose)
functions="$(sudo docker ps -aq --filter name=nuclio-nuclio-)"
if [ -n "$functions" ]; then
  sudo docker start $functions >/dev/null
fi

echo
echo "CVAT is running. On your own computer, run:"
echo "  ssh -L 8080:localhost:8080 medcvr@100.113.46.199"
echo "then open http://localhost:8080"
