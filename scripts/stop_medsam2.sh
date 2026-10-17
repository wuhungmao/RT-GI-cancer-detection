#!/usr/bin/env bash
# Stop the MedSAM2 web app and its container. Installed packages are kept.
# Usage: ./scripts/stop_medsam2.sh
set -euo pipefail

CONTAINER=medsam2

if sudo docker container inspect "$CONTAINER" >/dev/null 2>&1; then
  sudo docker stop "$CONTAINER" >/dev/null
  echo "MedSAM2 stopped."
else
  echo "Container $CONTAINER does not exist; nothing to stop."
fi
