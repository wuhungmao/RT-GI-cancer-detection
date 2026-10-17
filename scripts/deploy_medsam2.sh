#!/usr/bin/env bash
# Build and deploy the MedSAM2 interactor as a CVAT AI function on the AMD GPU.
# Needs CVAT running (./scripts/start_cvat.sh) and the CDI spec installed (see README).
# Usage: ./scripts/deploy_medsam2.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FUNC_DIR="$REPO_DIR/serverless/medsam2/nuclio"

if [ ! -e /etc/cdi/amd.yaml ]; then
  echo "AMD GPU CDI spec not installed. Run:"
  echo "  sudo mkdir -p /etc/cdi && sudo cp $REPO_DIR/gpu/amd-gpu-cdi.yaml /etc/cdi/amd.yaml"
  exit 1
fi

sudo nuctl create project cvat --platform local || true

echo "Deploying MedSAM2 (the first build takes a while and prints nothing during 'Building docker image')..."
sudo nuctl deploy --project-name cvat --path "$FUNC_DIR" \
  --file "$FUNC_DIR/function-gpu.yaml" --platform local \
  --platform-config '{"attributes": {"network": "cvat_cvat"}}'

sudo nuctl get function --platform local
