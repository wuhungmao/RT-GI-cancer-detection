import os

import numpy as np
import torch
from sam2.build_sam import build_sam2
from sam2.sam2_image_predictor import SAM2ImagePredictor


def mask_to_rle(mask):
    # Same format as CVAT's IOG interactor: run lengths starting with background,
    # followed by the mask's bounding box [left, top, right, bottom]
    height, width = mask.shape
    pixels = (np.asarray(mask).reshape(-1) != 0).astype(np.uint8)
    if pixels.size == 0:
        return []

    changes = np.flatnonzero(pixels[1:] != pixels[:-1]) + 1
    rle = np.diff(np.concatenate(([0], changes, [pixels.size]))).tolist()
    if pixels[0] == 1:
        rle.insert(0, 0)

    rle.extend([0, 0, width - 1, height - 1])
    return rle


class ModelHandler:
    def __init__(self):
        # On the ROCm build of PyTorch, the AMD GPU is reported as "cuda"
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        model = build_sam2(
            os.environ.get("MEDSAM2_CONFIG", "configs/sam2.1_hiera_t512.yaml"),
            os.environ.get("MEDSAM2_CHECKPOINT", "/opt/medsam2/checkpoints/MedSAM2_latest.pt"),
            device=self.device,
        )
        self.predictor = SAM2ImagePredictor(model)
        self.image_key = None

    def handle(self, image, pos_points, neg_points, obj_bbox):
        height, width = image.shape[:2]
        points = list(pos_points) + list(neg_points)
        if not points and len(obj_bbox) < 2:
            return np.zeros((height, width), dtype=np.uint8)

        with torch.inference_mode():
            # CVAT sends the whole image with every click; only re-encode when it changes
            key = hash(image.tobytes())
            if key != self.image_key:
                self.predictor.set_image(image)
                self.image_key = key

            point_coords = np.array(points, dtype=np.float32) if points else None
            point_labels = (
                np.array([1] * len(pos_points) + [0] * len(neg_points), dtype=np.int32)
                if points
                else None
            )
            box = None
            if len(obj_bbox) >= 2:
                (x1, y1), (x2, y2) = obj_bbox[0], obj_bbox[1]
                box = np.array(
                    [min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)], dtype=np.float32
                )

            masks, _, _ = self.predictor.predict(
                point_coords=point_coords,
                point_labels=point_labels,
                box=box,
                multimask_output=False,
            )

        return (masks[0] > 0).astype(np.uint8)
