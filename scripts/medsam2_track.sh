#!/usr/bin/env bash
# Propagate key-frame masks through a CVAT task with MedSAM2 on the AMD GPU.
# Annotate the key frame in CVAT first (e.g. with the MedSAM2 interactor), then:
# Usage: ./scripts/medsam2_track.sh <task-id> [--frame N] [--start N] [--stop N] [--replace]
# Set CVAT_USER / CVAT_PASSWORD to skip the login prompt.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE=rt-gi.medsam2:latest-gpu

if ! sudo docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Image $IMAGE not found. Build it first with ./scripts/deploy_medsam2.sh"
  exit 1
fi

# --network host: reach CVAT at localhost:8080; --gpus all: AMD GPU via the CDI spec
sudo docker run --rm -it --gpus all --network host \
  -e CVAT_URL="${CVAT_URL:-}" -e CVAT_USER="${CVAT_USER:-}" -e CVAT_PASSWORD="${CVAT_PASSWORD:-}" \
  -v "$REPO_DIR/scripts":/scripts:ro \
  --entrypoint python "$IMAGE" /scripts/medsam2_track.py "$@"
