#!/usr/bin/env bash
# Create (or update) the CVAT project with the study's object classes: Neoplasia, Dysplasia, Normal.
# Safe to re-run. Needs CVAT running and the MedSAM2 image (./scripts/deploy_medsam2.sh).
# Usage: ./scripts/setup_cvat_project.sh [--name "Project name"]
# Set CVAT_USER / CVAT_PASSWORD to skip the login prompt.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE=rt-gi.medsam2:latest-gpu

if ! sudo docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Image $IMAGE not found. Build it first with ./scripts/deploy_medsam2.sh"
  exit 1
fi

# --network host: reach CVAT at localhost:8080
sudo docker run --rm -it --network host \
  -e CVAT_URL="${CVAT_URL:-}" -e CVAT_USER="${CVAT_USER:-}" -e CVAT_PASSWORD="${CVAT_PASSWORD:-}" \
  -v "$REPO_DIR/scripts":/scripts:ro \
  --entrypoint python "$IMAGE" /scripts/setup_cvat_project.py "$@"
