#!/usr/bin/env bash
# Build and deploy the TransT tracker for CVAT on the AMD GPU (replaces the CPU version).
# Needs CVAT running (./scripts/start_cvat.sh) and the CDI spec installed (see README).
# Usage: ./scripts/deploy_transt.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Code from CVAT's TransT function, build config from our ROCm version
CODE_DIR="$REPO_DIR/cvat/serverless/pytorch/dschoerk/transt/nuclio"
CONFIG="$REPO_DIR/serverless/transt/nuclio/function-gpu.yaml"

if [ ! -e /etc/cdi/amd.yaml ]; then
  echo "AMD GPU CDI spec not installed. Run:"
  echo "  sudo mkdir -p /etc/cdi && sudo cp $REPO_DIR/gpu/amd-gpu-cdi.yaml /etc/cdi/amd.yaml"
  exit 1
fi

sudo nuctl create project cvat --platform local || true

echo "Deploying TransT (the first build takes a while and prints nothing during 'Building docker image')..."
sudo nuctl deploy --project-name cvat --path "$CODE_DIR" \
  --file "$CONFIG" --platform local \
  --platform-config '{"attributes": {"network": "cvat_cvat"}}'

sudo nuctl get function --platform local
