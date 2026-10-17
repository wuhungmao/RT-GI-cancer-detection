"""Propagate key-frame annotations through a CVAT task with MedSAM2.

Every mask, polygon and rectangle on the key frame becomes one tracked object.
MedSAM2 follows each object forward and backward through the task's frames,
and the resulting masks are uploaded back to the task.

Runs inside the MedSAM2 function image; use scripts/medsam2_track.sh to start it.
"""

import argparse
import getpass
import os
import tempfile

import numpy as np
import torch
from PIL import Image, ImageDraw

DEFAULT_CONFIG = "configs/sam2.1_hiera_t512.yaml"
DEFAULT_CHECKPOINT = "/opt/medsam2/checkpoints/MedSAM2_latest.pt"
KEY_SHAPE_TYPES = ("mask", "polygon", "rectangle")
UPLOAD_BATCH = 200


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


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("task_id", type=int, help="CVAT task ID")
    parser.add_argument("--frame", type=int, help="key frame (default: first frame with a mask or polygon)")
    parser.add_argument("--start", type=int, help="first frame to process (default: task start)")
    parser.add_argument("--stop", type=int, help="last frame to process (default: task end)")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="delete existing masks of the tracked labels on the processed frames (except the key frame) first",
    )
    parser.add_argument("--url", default=os.environ.get("CVAT_URL") or "http://localhost:8080")
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--checkpoint", default=DEFAULT_CHECKPOINT)
    return parser.parse_args()


def pick_key_shapes(shapes, key_frame):
    if key_frame is None:
        frames = [s.frame for s in shapes if s.type.value in ("mask", "polygon")]
        if not frames:
            raise SystemExit("No mask or polygon annotations found. Annotate the key frame first, or pass --frame.")
        key_frame = min(frames)

    key_shapes = [s for s in shapes if s.frame == key_frame and s.type.value in KEY_SHAPE_TYPES]
    if not key_shapes:
        raise SystemExit(f"No mask, polygon or rectangle annotations on frame {key_frame}.")
    return key_frame, key_shapes


def main():
    from cvat_sdk import make_client
    from cvat_sdk.api_client import models
    from cvat_sdk.core.proxies.annotations import AnnotationUpdateAction
    from sam2.build_sam import build_sam2_video_predictor

    args = parse_args()
    user = os.environ.get("CVAT_USER") or input("CVAT username: ")
    password = os.environ.get("CVAT_PASSWORD") or getpass.getpass("CVAT password: ")

    with make_client(args.url, credentials=(user, password)) as client:
        task = client.tasks.retrieve(args.task_id)
        start = args.start if args.start is not None else 0
        stop = args.stop if args.stop is not None else task.size - 1
        if not 0 <= start <= stop < task.size:
            raise SystemExit(f"Frame range must be within 0..{task.size - 1}")

        annotations = task.get_annotations()
        key_frame, key_shapes = pick_key_shapes(annotations.shapes, args.frame)
        if not start <= key_frame <= stop:
            raise SystemExit(f"Key frame {key_frame} is outside the processed range {start}..{stop}")

        labels = {label.id: label.name for label in task.get_labels()}
        print(f"Task {task.id} '{task.name}': frames {start}..{stop}, key frame {key_frame}")
        for i, shape in enumerate(key_shapes):
            print(f"  object {i}: {shape.type.value} '{labels.get(shape.label_id, shape.label_id)}'")

        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Loading MedSAM2 on {device}")
        predictor = build_sam2_video_predictor(args.config, args.checkpoint, device=device)

        new_shapes = []
        with tempfile.TemporaryDirectory() as frames_dir, torch.inference_mode():
            print(f"Downloading {stop - start + 1} frames...")
            for frame in range(start, stop + 1):
                image = Image.open(task.get_frame(frame, quality="original")).convert("RGB")
                # MedSAM2 reads a folder of JPEGs sorted by name
                image.save(os.path.join(frames_dir, f"{frame - start:07d}.jpg"), quality=95)

            state = predictor.init_state(video_path=frames_dir, offload_video_to_cpu=True)
            height, width = state["video_height"], state["video_width"]
            key_idx = key_frame - start

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

            for reverse in (False, True):
                if reverse and key_idx == 0:
                    continue
                print("Propagating " + ("backward" if reverse else "forward") + "...")
                for frame_idx, obj_ids, mask_logits in predictor.propagate_in_video(
                    state, start_frame_idx=key_idx, reverse=reverse
                ):
                    if frame_idx == key_idx:
                        continue
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
                                source="semi-auto",
                            )
                        )

        if args.replace:
            tracked_labels = {s.label_id for s in key_shapes}
            old_ids = [
                s.id
                for s in annotations.shapes
                if s.type.value == "mask"
                and s.label_id in tracked_labels
                and start <= s.frame <= stop
                and s.frame != key_frame
            ]
            if old_ids:
                print(f"Removing {len(old_ids)} existing masks...")
                task.remove_annotations(ids=old_ids)

        print(f"Uploading {len(new_shapes)} masks...")
        for i in range(0, len(new_shapes), UPLOAD_BATCH):
            task.update_annotations(
                models.PatchedLabeledDataRequest(shapes=new_shapes[i : i + UPLOAD_BATCH]),
                action=AnnotationUpdateAction.CREATE,
            )
        print(f"Done. Open task {task.id} in CVAT to review the masks.")


if __name__ == "__main__":
    main()
