"""MedSAM2 tracking of CVAT annotations, shared by the tracker service and the CLI.

Every mask, polygon and rectangle on the key frame becomes one tracked object.
MedSAM2 follows each object forward and backward through the frame range,
and the resulting masks are uploaded with source "auto".
"""

import os
import tempfile
from types import SimpleNamespace

import numpy as np
import torch
from cvat_sdk.api_client import models
from cvat_sdk.core.proxies.annotations import AnnotationUpdateAction
from PIL import Image, ImageDraw

DEFAULT_CONFIG = "configs/sam2.1_hiera_t512.yaml"
DEFAULT_CHECKPOINT = "/opt/medsam2/checkpoints/MedSAM2_latest.pt"
KEY_SHAPE_TYPES = ("mask", "polygon", "rectangle")
# Masks created by tracking; --replace / "replace" only removes these, never manual edits
TRACKED_SOURCE = "auto"
UPLOAD_BATCH = 200


class TrackingError(Exception):
    pass


def load_predictor(config=DEFAULT_CONFIG, checkpoint=DEFAULT_CHECKPOINT):
    from sam2.build_sam import build_sam2_video_predictor

    # On the ROCm build of PyTorch, the AMD GPU is reported as "cuda"
    device = "cuda" if torch.cuda.is_available() else "cpu"
    return build_sam2_video_predictor(config, checkpoint, device=device), device


def cvat_mask_to_array(points, height, width):
    # CVAT mask points: run lengths (starting with background) over the mask's
    # bounding box, followed by the box itself [left, top, right, bottom]
    *rle, left, top, right, bottom = points
    left, top, right, bottom = int(left), int(top), int(right), int(bottom)
    box_w, box_h = right - left + 1, bottom - top + 1

    flat = np.zeros(box_w * box_h, dtype=np.uint8)
    pos, value = 0, 0
    for run in rle:
        run = int(run)
        if value:
            flat[pos : pos + run] = 1
        pos += run
        value ^= 1

    mask = np.zeros((height, width), dtype=np.uint8)
    mask[top : bottom + 1, left : right + 1] = flat.reshape(box_h, box_w)
    return mask


def array_to_cvat_mask(mask):
    ys, xs = np.nonzero(mask)
    if ys.size == 0:
        return None
    top, bottom, left, right = ys.min(), ys.max(), xs.min(), xs.max()
    pixels = mask[top : bottom + 1, left : right + 1].reshape(-1).astype(np.uint8)

    changes = np.flatnonzero(pixels[1:] != pixels[:-1]) + 1
    rle = np.diff(np.concatenate(([0], changes, [pixels.size]))).tolist()
    if pixels[0] == 1:
        rle.insert(0, 0)
    return [float(v) for v in rle] + [float(left), float(top), float(right), float(bottom)]


def polygon_to_array(points, height, width):
    image = Image.new("L", (width, height), 0)
    ImageDraw.Draw(image).polygon(list(zip(points[0::2], points[1::2])), fill=1)
    return np.array(image, dtype=np.uint8)


def describe_annotations(annotations):
    def frame_ranges(frames):
        frames = sorted(set(frames))
        ranges, first = [], frames[0]
        for prev, cur in zip(frames, frames[1:] + [None]):
            if cur != prev + 1:
                ranges.append(str(first) if first == prev else f"{first}-{prev}")
                first = cur
        return ", ".join(ranges)

    frames_by_type = {}
    for shape in annotations.shapes:
        frames_by_type.setdefault(shape.type.value, []).append(shape.frame)
    for track_ in annotations.tracks:
        for shape in track_.shapes:
            frames_by_type.setdefault(f"{shape.type.value} (track)", []).append(shape.frame)

    lines = [
        f"  {what} on frame{'s' if len(set(frames)) > 1 else ''} {frame_ranges(frames)}"
        for what, frames in sorted(frames_by_type.items())
    ]
    return "\n".join(lines) or "  nothing (were the annotations saved?)"


def key_frame_shapes(annotations, key_frame):
    """Masks, polygons and rectangles on the key frame, from shapes and from tracks (Track mode)."""
    key_shapes = [s for s in annotations.shapes if s.frame == key_frame and s.type.value in KEY_SHAPE_TYPES]
    for track_ in annotations.tracks:
        for shape in track_.shapes:
            if shape.frame == key_frame and not shape.outside and shape.type.value in KEY_SHAPE_TYPES:
                key_shapes.append(
                    SimpleNamespace(type=shape.type, points=shape.points, frame=key_frame, label_id=track_.label_id)
                )
    return key_shapes


def pick_key_shapes(annotations, key_frame):
    if key_frame is None:
        frames = [s.frame for s in annotations.shapes if s.type.value in ("mask", "polygon")]
        if not frames:
            raise TrackingError(
                "No mask or polygon annotations found. Annotate the key frame first.\n"
                "Annotations found:\n" + describe_annotations(annotations)
            )
        key_frame = min(frames)

    key_shapes = key_frame_shapes(annotations, key_frame)
    if not key_shapes:
        raise TrackingError(
            f"Frame {key_frame} has no mask, polygon or box to track. Draw one on this frame and try again.\n"
            "Annotations found:\n" + describe_annotations(annotations)
        )
    return key_frame, key_shapes


def track(source, predictor, start, stop, key_frame=None, replace=False, progress=None):
    """Track key-frame objects of a CVAT task or job (cvat_sdk proxy) over frames start..stop.

    progress(stage, done, total) is called as work proceeds.
    Returns (key_frame, key_shapes, number of masks uploaded).
    """
    progress = progress or (lambda stage, done, total: None)

    annotations = source.get_annotations()
    key_frame, key_shapes = pick_key_shapes(annotations, key_frame)
    if not start <= key_frame <= stop:
        raise TrackingError(f"Key frame {key_frame} is outside the frame range {start}..{stop}")

    num_frames = stop - start + 1
    key_idx = key_frame - start
    new_shapes = []
    with tempfile.TemporaryDirectory() as frames_dir, torch.inference_mode():
        for i, frame in enumerate(range(start, stop + 1)):
            progress("Downloading frames", i, num_frames)
            image = Image.open(source.get_frame(frame, quality="original")).convert("RGB")
            # MedSAM2 reads a folder of JPEGs sorted by name
            image.save(os.path.join(frames_dir, f"{i:07d}.jpg"), quality=95)

        progress("Loading frames into MedSAM2", 0, 1)
        state = predictor.init_state(video_path=frames_dir, offload_video_to_cpu=True)
        try:
            height, width = state["video_height"], state["video_width"]
            for obj_id, shape in enumerate(key_shapes):
                if shape.type.value == "rectangle":
                    predictor.add_new_points_or_box(
                        state, frame_idx=key_idx, obj_id=obj_id, box=np.array(shape.points, dtype=np.float32)
                    )
                else:
                    if shape.type.value == "mask":
                        mask = cvat_mask_to_array(shape.points, height, width)
                    else:
                        mask = polygon_to_array(shape.points, height, width)
                    predictor.add_new_mask(state, frame_idx=key_idx, obj_id=obj_id, mask=mask.astype(bool))

            done = 0
            for reverse in (False, True):
                if reverse and key_idx == 0:
                    continue
                for frame_idx, obj_ids, mask_logits in predictor.propagate_in_video(
                    state, start_frame_idx=key_idx, reverse=reverse
                ):
                    if frame_idx == key_idx:
                        continue
                    done += 1
                    progress("Tracking", done, num_frames - 1)
                    for i, obj_id in enumerate(obj_ids):
                        points = array_to_cvat_mask((mask_logits[i, 0] > 0.0).cpu().numpy())
                        if points is None:
                            continue
                        new_shapes.append(
                            models.LabeledShapeRequest(
                                type=models.ShapeType("mask"),
                                frame=frame_idx + start,
                                label_id=key_shapes[obj_id].label_id,
                                points=points,
                                occluded=False,
                                z_order=0,
                                rotation=0.0,
                                attributes=[],
                                group=0,
                                source=TRACKED_SOURCE,
                            )
                        )
        finally:
            del state
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    if replace:
        tracked_labels = {s.label_id for s in key_shapes}
        old_ids = [
            s.id
            for s in annotations.shapes
            if s.type.value == "mask"
            and s.source == TRACKED_SOURCE
            and s.label_id in tracked_labels
            and start <= s.frame <= stop
            and s.frame != key_frame
        ]
        if old_ids:
            progress("Removing previous tracking results", 0, 1)
            source.remove_annotations(ids=old_ids)

    for i in range(0, len(new_shapes), UPLOAD_BATCH):
        progress("Uploading masks", i, len(new_shapes))
        source.update_annotations(
            models.PatchedLabeledDataRequest(shapes=new_shapes[i : i + UPLOAD_BATCH]),
            action=AnnotationUpdateAction.CREATE,
        )
    return key_frame, key_shapes, len(new_shapes)
