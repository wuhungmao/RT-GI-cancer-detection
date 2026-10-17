# RT-GI-cancer-detection

## Quick start

On the server, from the `RT-GI-cancer-detection` folder:

```bash
./scripts/start_cvat.sh       # starts CVAT in the background
./scripts/start_medsam2.sh    # starts the MedSAM2 web app (Ctrl+C to stop)

./scripts/deploy_medsam2.sh   # builds MedSAM2 for CVAT (interactor + "Track with MedSAM2") on the AMD GPU (once, CVAT must be running)
./scripts/deploy_transt.sh    # builds the TransT tracker on the AMD GPU (once, replaces the CPU version)
./scripts/medsam2_track.sh <task-id>   # propagates key-frame masks through a CVAT task with MedSAM2

./scripts/stop_cvat.sh        # stops CVAT and its AI models (data is kept)
./scripts/stop_medsam2.sh     # stops the MedSAM2 container
```

Each script prints the `ssh -L` command to run on your own computer to open the page. The sections below explain each step.

## Installing MedSAM2

Below are the commands I used to build MedSAM2.

> **Note:** This conda setup uses an NVIDIA build of PyTorch, so on our AMD server it runs on **CPU only**. To use the AMD GPU, follow [Running MedSAM2 on the server](#running-medsam2-on-the-server) instead.

### 1. Install conda (Miniforge)

```bash
wget https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh
bash Miniforge3-Linux-x86_64.sh
~/miniforge3/bin/conda init bash
```

### 2. Create the environment

```bash
conda create -n medsam2 python=3.12 -y
conda activate medsam2
```

### 3. PyTorch

```bash
pip install torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cu124
```

### 4. MedSAM2 code

```bash
git clone https://github.com/bowang-lab/MedSAM2.git && cd MedSAM2
pip install setuptools
SAM2_BUILD_CUDA=0 pip install --no-build-isolation -e ".[dev]"
pip install opencv-python matplotlib
```

### 5. Checkpoints

```bash
bash download.sh
wget -P checkpoints https://huggingface.co/wanglab/MedSAM2/resolve/main/MedSAM2_2411.pt
```

### 6. Web app (`app.py`) dependencies

```bash
sudo apt-get install ffmpeg
pip install gradio==3.38.0 numpy==1.26.3 ffmpeg-python moviepy
pip install "gradio_client==0.2.10" "setuptools<81" "fastapi==0.110.3"
```

---

## Running MedSAM2 on the server

MedSAM2 runs inside a Docker container (`rocm/pytorch` image) so it can use the server's AMD GPU.

### 1. Start the container

Start the existing container:

```bash
sudo docker start -ai medsam2
```

If the container does not exist yet (first time only), create it:

```bash
sudo docker run -it --name medsam2 \
  --device=/dev/kfd --device=/dev/dri \
  --group-add $(getent group render | cut -d: -f3) --group-add video \
  --ipc=host --security-opt seccomp=unconfined \
  -p 18862:18862 \
  -v ~/RT-GI-cancer-detection:/workspace \
  -w /workspace/MedSAM2 \
  rocm/pytorch:rocm7.2.1_ubuntu24.04_py3.12_pytorch_release_2.9.1
```

### 2. Check that PyTorch sees the AMD GPU

Inside the container:

```bash
python -c "import torch; print(torch.__version__, torch.version.hip, torch.cuda.is_available())"
```

It should print a ROCm version, a HIP version, and `True`.

### 3. Install MedSAM2 inside the container (first time only)

This locks PyTorch so pip does not replace the AMD build:

```bash
pip freeze | grep -iE "^(torch|torchvision|torchaudio|triton|pytorch-triton)" > /tmp/keep.txt
SAM2_BUILD_CUDA=0 pip install --no-build-isolation -e ".[dev]" -c /tmp/keep.txt
apt-get update && apt-get install -y ffmpeg
pip install -c /tmp/keep.txt gradio==3.38.0 numpy==1.26.3 ffmpeg-python moviepy \
  "gradio_client==0.2.10" "setuptools<81" "fastapi==0.110.3" opencv-python matplotlib
```

### 4. Start the app

```bash
cd /workspace/MedSAM2
python app.py
```

### 5. Forward the port to your computer

Open a terminal on your local laptop/computer:

```bash
ssh -L 18862:localhost:18862 medcvr@100.113.46.199
```

Then go to Chrome (or another browser) and enter:

```
http://localhost:18862/?__theme=light
```

You should see the MedSAM2 page.

---

## How to use MedSAM2

1. Upload a video.
2. Select **sam2.1_hiera_t512** for "Select Config File".
3. Select **MedSAM2_latest** for "Select Checkpoint File".
4. Click **Preprocess**.
5. After MedSAM2 splits the video into frames, the first frame appears in the box below.
6. Draw the prompt area (bounding box) with **Stroke to Box Prompt**, or click with **Point Prompt**.
   - Sometimes there is a bug where only part of the first frame is shown. If that happens, use the other prompt method.
7. Click **Start Tracking** to turn the raw video into an annotated video.

You can check the progress in the terminal.

---

## Running CVAT on the server

CVAT is in the `cvat` folder (a submodule) and runs with Docker Compose.

### 0. Let Docker use the AMD GPU (once per server)

CVAT's AI models (Nuclio functions) can only ask Docker for a GPU with `--gpus all`.
This CDI file tells Docker which device files that means on our AMD server:

```bash
sudo mkdir -p /etc/cdi
sudo cp gpu/amd-gpu-cdi.yaml /etc/cdi/amd.yaml
```

Check that it works (should print `True`):

```bash
sudo docker run --rm --gpus all rocm/pytorch:rocm7.2.1_ubuntu24.04_py3.12_pytorch_release_2.9.1 \
  python -c "import torch; print(torch.cuda.is_available())"
```

### 1. Log in to the server

```bash
ssh medcvr@100.113.46.199
```

### 2. Start CVAT

```bash
cd ~/RT-GI-cancer-detection
./scripts/start_cvat.sh
```

This builds and starts CVAT with our additions (`docker-compose.medsam2.yml`): the "Track with MedSAM2"
UI plugin and, once `./scripts/deploy_medsam2.sh` has been run, the tracker service behind it.
The first build takes a while. Later starts are faster.

To stop CVAT:

```bash
./scripts/stop_cvat.sh
```

> **Warning:** Always start and stop CVAT with these scripts. If you run `docker compose` by hand, include all four
> compose files (see `scripts/cvat_compose.sh`), and never add `-v` to `down`: it deletes all CVAT data and annotations.

### 3. Create an admin account (first time only)

```bash
sudo docker exec -it cvat_server bash -ic 'python3 ~/manage.py createsuperuser'
```

### 4. Forward the port to your computer

Open a terminal on your local laptop/computer:

```bash
ssh -L 8080:localhost:8080 medcvr@100.113.46.199
```

Then go to Chrome (or another browser) and enter:

```
http://localhost:8080
```

You should see the CVAT login page.

---

## Tracking with MedSAM2 in CVAT

Setup (once, on the server): `./scripts/start_cvat.sh`, then `./scripts/deploy_medsam2.sh`.

MedSAM2 is available in CVAT in two ways, both entirely in the browser:

- **Interactor**: segments one object on the current frame.
  In a job, open **AI Tools → Interactors → MedSAM2**, draw a box around the object
  and/or click positive and negative points, then press **N** to keep the mask.
- **Track with MedSAM2**: copies the masks on the current frame to the other frames of the job.

### Tracking an object through a video

1. Create a CVAT task from the video. Use a frame step (e.g. 25 for a 25 fps video, so 1 frame per second)
   to keep the number of frames manageable.
2. Open the job and go to the frame where the object is clearly visible.
3. Annotate each object to track with a mask, polygon or box
   (the MedSAM2 interactor is the quickest way to get a mask).
4. Open **Menu** (top left) → **Track with MedSAM2**, check the frame range, and click **Start tracking**.
   Unsaved annotations are saved automatically first.
5. A progress bar shows downloading, tracking and uploading. You can close the window and keep working;
   a message appears when tracking finishes and the new masks are loaded into the job automatically.
6. Review the masks and fix frames where the tracking drifted.

**Replace masks from earlier MedSAM2 tracking** (on by default) removes masks from previous tracking runs
of the same labels before adding the new ones, so you can re-run tracking after fixing the key frame.
Masks you drew or edited yourself are never removed.

Tracking runs one at a time on the GPU. If someone else is tracking, the progress window says so and yours starts next.

### Tracking from the terminal

The same tracking for a whole task (task ID from the task URL, e.g. `/tasks/12`):

```bash
./scripts/medsam2_track.sh 12            # asks for your CVAT username and password
./scripts/medsam2_track.sh 12 --replace  # remove masks from earlier tracking runs first
```

Other options: `--frame N` (key frame; default: the first frame with a mask or polygon),
`--start N` / `--stop N` (only process frames N to M).