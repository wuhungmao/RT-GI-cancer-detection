"""Propagate key-frame annotations through a CVAT task with MedSAM2 (terminal version).

Every mask, polygon and rectangle on the key frame becomes one tracked object.
MedSAM2 follows each object forward and backward through the task's frames,
and the resulting masks are uploaded back to the task.

Runs inside the MedSAM2 function image; use scripts/medsam2_track.sh to start it.
The same tracking is available in the CVAT UI (Menu -> Track with MedSAM2).
"""

import argparse
import getpass
import os

from cvat_sdk import make_client

from medsam2_tracking import DEFAULT_CHECKPOINT, DEFAULT_CONFIG, TrackingError, load_predictor, track


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("task_id", type=int, help="CVAT task ID")
    parser.add_argument("--frame", type=int, help="key frame (default: first frame with a mask or polygon)")
    parser.add_argument("--start", type=int, help="first frame to process (default: task start)")
    parser.add_argument("--stop", type=int, help="last frame to process (default: task end)")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="delete masks from previous tracking runs (same labels, except the key frame) first",
    )
    parser.add_argument("--url", default=os.environ.get("CVAT_URL") or "http://localhost:8080")
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--checkpoint", default=DEFAULT_CHECKPOINT)
    return parser.parse_args()


def main():
    args = parse_args()
    user = os.environ.get("CVAT_USER") or input("CVAT username: ")
    password = os.environ.get("CVAT_PASSWORD") or getpass.getpass("CVAT password: ")

    with make_client(args.url, credentials=(user, password)) as client:
        task = client.tasks.retrieve(args.task_id)
        start = args.start if args.start is not None else 0
        stop = args.stop if args.stop is not None else task.size - 1
        if not 0 <= start <= stop < task.size:
            raise SystemExit(f"Frame range must be within 0..{task.size - 1}")

        predictor, device = load_predictor(args.config, args.checkpoint)
        print(f"Task {task.id} '{task.name}': frames {start}..{stop}, MedSAM2 on {device}")

        last_stage = None

        def progress(stage, done, total):
            nonlocal last_stage
            if stage != last_stage:
                print(stage + "...")
                last_stage = stage

        try:
            key_frame, key_shapes, uploaded = track(
                task, predictor, start, stop, key_frame=args.frame, replace=args.replace, progress=progress
            )
        except TrackingError as e:
            raise SystemExit(str(e))

        print(f"Done: tracked {len(key_shapes)} object(s) from frame {key_frame}, uploaded {uploaded} masks.")
        print(f"Open task {task.id} in CVAT to review them.")


if __name__ == "__main__":
    main()
