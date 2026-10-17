#!/usr/bin/env bash
# Stop CVAT and its Nuclio AI model containers. Annotation data is kept.
# Usage: ./scripts/stop_cvat.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR/cvat"

# AI model containers are started by Nuclio, not by docker compose
functions="$(sudo docker ps -q --filter name=nuclio-nuclio-)"
if [ -n "$functions" ]; then
  sudo docker stop $functions
fi

# No -v here: -v would delete the volumes with all CVAT data
sudo docker compose \
  -f docker-compose.yml \
  -f docker-compose.dev.yml \
  -f components/serverless/docker-compose.serverless.yml \
  down

echo "CVAT stopped."
