# RT-GI-cancer-detection

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