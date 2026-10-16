# RT-GI-cancer-detection

----------------------Installing MedSAM2-----------------
Below are the commands I use to build MedSam2:
# 1. Install conda (Miniforge)
wget https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh
bash Miniforge3-Linux-x86_64.sh
~/miniforge3/bin/conda init bash

# 2. Create the environment
conda create -n medsam2 python=3.12 -y
conda activate medsam2

# 3. PyTorch
pip install torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cu124

# 4. MedSAM2 code
git clone https://github.com/bowang-lab/MedSAM2.git && cd MedSAM2
pip install setuptools
SAM2_BUILD_CUDA=0 pip install --no-build-isolation -e ".[dev]"
pip install opencv-python matplotlib

# 5. Checkpoints
bash download.sh
wget -P checkpoints https://huggingface.co/wanglab/MedSAM2/resolve/main/MedSAM2_2411.pt

# 6. Web app (app.py) dependencies
sudo apt-get install ffmpeg
pip install gradio==3.38.0 numpy==1.26.3 ffmpeg-python moviepy
pip install "gradio_client==0.2.10" "setuptools<81" "fastapi==0.110.3"


------------------Running MedSAM2 on the server----------
MedSAM2 runs inside a Docker container (rocm/pytorch image) so it can use the server's AMD GPU.
The conda environment from the install section uses an NVIDIA build of PyTorch and runs on CPU only.

Start the existing container:
sudo docker start -ai medsam2

If the container does not exist yet (first time only), create it:
sudo docker run -it --name medsam2 \
  --device=/dev/kfd --device=/dev/dri \
  --group-add $(getent group render | cut -d: -f3) --group-add video \
  --ipc=host --security-opt seccomp=unconfined \
  -p 18862:18862 \
  -v ~/RT-GI-cancer-detection:/workspace \
  -w /workspace/MedSAM2 \
  rocm/pytorch:rocm7.2.1_ubuntu24.04_py3.12_pytorch_release_2.9.1

Inside the container, check that PyTorch sees the AMD GPU:
python -c "import torch; print(torch.__version__, torch.version.hip, torch.cuda.is_available())"
It should print a ROCm version, a HIP version, and True.

First time only, install MedSAM2 inside the container (locks PyTorch so pip does not replace the AMD build):
pip freeze | grep -iE "^(torch|torchvision|torchaudio|triton|pytorch-triton)" > /tmp/keep.txt
SAM2_BUILD_CUDA=0 pip install --no-build-isolation -e ".[dev]" -c /tmp/keep.txt
apt-get update && apt-get install -y ffmpeg
pip install -c /tmp/keep.txt gradio==3.38.0 numpy==1.26.3 ffmpeg-python moviepy \
  "gradio_client==0.2.10" "setuptools<81" "fastapi==0.110.3" opencv-python matplotlib


Then start the app:
cd /workspace/MedSAM2
python app.py

Then forward port 18862 from the server to your laptop/computer.
Open a terminal on your local laptop/computer:
ssh -L 18862:localhost:18862 medcvr@100.113.46.199

Go to Chrome (or another browser) and enter:
http://localhost:18862/?__theme=light

You should see the MedSAM2 page.

---------------------How to use MedSAM2---------------------------
1. Upload videos 
2. select sam2.1_hiera_t512 for "Select Config File"
3. Select MedSAM2_latest for "Select Checkpoint File"
4. Click preprocess
5. Then you should see first frame shown on the box below, after MedSAM2 segments the video into frames
6. Either draw the prompt area(boundary box) with "Stroke to Box Prompt" or "Point Prompt" (sometimes there is a bug where you only see a part of first frame, in which case, choose the other way of drawing the prompt)
7. Click Start Tracking to convert the raw video into an annotated video

ps. You can check the progress on terminal
