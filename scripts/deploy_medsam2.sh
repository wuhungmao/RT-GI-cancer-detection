#!/usr/bin/env bash
# Build and deploy the MedSAM2 interactor as a CVAT AI function on the AMD GPU,
# and (re)start the tracker service behind "Track with MedSAM2", which uses the same image.
# Needs CVAT running (./scripts/start_cvat.sh) and the CDI spec installed (see README).
# Usage: ./scripts/deploy_medsam2.sh
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/cvat_compose.sh"
FUNC_DIR="$REPO_DIR/cvat-integration/nuclio-functions/medsam2"

if [ ! -e /etc/cdi/amd.yaml ]; then
  echo "AMD GPU CDI spec not installed. Run:"
  echo "  sudo mkdir -p /etc/cdi && sudo cp $REPO_DIR/config/amd-gpu-cdi.yaml /etc/cdi/amd.yaml"
  exit 1
fi

sudo nuctl create project cvat --platform local || true

echo "Deploying MedSAM2 (the first build takes a while and prints nothing during 'Building docker image')..."
sudo nuctl deploy --project-name cvat --path "$FUNC_DIR" \
  --file "$FUNC_DIR/function-gpu.yaml" --platform local \
  --platform-config '{"attributes": {"network": "cvat_cvat"}}'

sudo nuctl get function --platform local

echo "Starting the MedSAM2 tracker service..."
cvat_compose up -d medsam2_tracker
