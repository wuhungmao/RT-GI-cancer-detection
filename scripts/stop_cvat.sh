#!/usr/bin/env bash
# Stop CVAT, its Nuclio AI model containers and the MedSAM2 tracker. Annotation data is kept.
# Usage: ./scripts/stop_cvat.sh
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/cvat_compose.sh"

# AI model containers are started by Nuclio, not by docker compose
functions="$(sudo docker ps -q --filter name=nuclio-nuclio-)"
if [ -n "$functions" ]; then
  sudo docker stop $functions
fi

# No -v here: -v would delete the volumes with all CVAT data
cvat_compose down

echo "CVAT stopped."
