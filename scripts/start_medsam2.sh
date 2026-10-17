#!/usr/bin/env bash
# Start the MedSAM2 web app inside the medsam2 Docker container (AMD GPU).
# Usage: ./scripts/start_medsam2.sh   (Ctrl+C stops the app; the container keeps running)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTAINER=medsam2
IMAGE=rocm/pytorch:rocm7.2.1_ubuntu24.04_py3.12_pytorch_release_2.9.1

if ! sudo docker container inspect "$CONTAINER" >/dev/null 2>&1; then
  echo "Creating container $CONTAINER..."
  sudo docker run -dit --name "$CONTAINER" \
    --device=/dev/kfd --device=/dev/dri \
    --group-add "$(getent group render | cut -d: -f3)" --group-add video \
    --ipc=host --security-opt seccomp=unconfined \
    -p 18862:18862 \
    -v "$REPO_DIR":/workspace \
    -w /workspace/MedSAM2 \
    "$IMAGE"
else
  sudo docker start "$CONTAINER" >/dev/null
fi

if ! sudo docker exec "$CONTAINER" python -c "import sam2, gradio" >/dev/null 2>&1; then
  echo "MedSAM2 is not installed in the container yet."
  echo "Run step 3 of \"Running MedSAM2 on the server\" in README.md inside the container:"
  echo "  sudo docker exec -it $CONTAINER bash"
  exit 1
fi

echo "Starting MedSAM2. On your own computer, run:"
echo "  ssh -L 18862:localhost:18862 medcvr@100.113.46.199"
echo "then open http://localhost:18862/?__theme=light"
echo

sudo docker exec -it -w /workspace/MedSAM2 "$CONTAINER" python app.py
