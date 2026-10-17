#!/usr/bin/env bash
# Start CVAT with Nuclio (needed for AI tools) and the MedSAM2 tracking plugin in the background.
# Usage: ./scripts/start_cvat.sh
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/cvat_compose.sh"

# The CVAT UI build only sees files inside the cvat folder, so copy our plugin there
PLUGIN_DIR="$REPO_DIR/cvat/cvat-ui/plugins/medsam2-tracker"
rm -rf "$PLUGIN_DIR"
cp -r "$REPO_DIR/cvat-plugins/medsam2-tracker" "$PLUGIN_DIR"
# ...and keep the copy out of the cvat submodule's git status
exclude="$(git -C "$REPO_DIR/cvat" rev-parse --absolute-git-dir)/info/exclude"
mkdir -p "$(dirname "$exclude")"
grep -qxF "/cvat-ui/plugins/medsam2-tracker/" "$exclude" 2>/dev/null \
  || echo "/cvat-ui/plugins/medsam2-tracker/" >> "$exclude"

cvat_compose up -d --build

# Restart AI model containers stopped by stop_cvat.sh (deployed with nuctl, not compose)
functions="$(sudo docker ps -aq --filter name=nuclio-nuclio-)"
if [ -n "$functions" ]; then
  sudo docker start $functions >/dev/null
fi

echo
if ! sudo docker image inspect "$MEDSAM2_IMAGE" >/dev/null 2>&1; then
  echo "Note: \"Track with MedSAM2\" needs ./scripts/deploy_medsam2.sh to be run once."
fi
echo "CVAT is running. On your own computer, run:"
echo "  ssh -L 8080:localhost:8080 medcvr@100.113.46.199"
echo "then open http://localhost:8080"
