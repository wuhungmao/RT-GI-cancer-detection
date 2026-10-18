#!/usr/bin/env bash
# Shared by the other scripts (source it, don't run it): runs `docker compose` for CVAT
# with our additions. Usage after sourcing: cvat_compose up -d
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MEDSAM2_IMAGE=rt-gi.medsam2:latest-gpu

cvat_compose() {
  local profile=()
  # The tracker service needs the MedSAM2 image from scripts/deploy_medsam2.sh
  if sudo docker image inspect "$MEDSAM2_IMAGE" >/dev/null 2>&1; then
    profile=(--profile medsam2)
  fi

  (
    cd "$REPO_DIR/cvat"
    sudo RT_GI_REPO_DIR="$REPO_DIR" docker compose \
      -f docker-compose.yml \
      -f docker-compose.dev.yml \
      -f components/serverless/docker-compose.serverless.yml \
      -f "$REPO_DIR/config/docker-compose.medsam2.yml" \
      "${profile[@]}" "$@"
  )
}
