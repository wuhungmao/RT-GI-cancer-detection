"""Create (or update) the CVAT project that holds the study's object classes.

Every task created inside the project gets these labels automatically.
Safe to re-run: missing labels are added, existing labels and annotations are left untouched.

Runs inside the MedSAM2 function image (it has the CVAT SDK); use scripts/setup_cvat_project.sh to start it.
"""

import argparse
import getpass
import os

from cvat_sdk import make_client
from cvat_sdk.api_client import models

PROJECT_NAME = "GI cancer detection"
# (name, type, color); type "any" allows masks, polygons and boxes
LABELS = [
    ("Neoplasia", "any", "#e6194b"),
    ("Dysplasia", "any", "#f58231"),
    ("Normal", "any", "#3cb44b"),
]


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", default=PROJECT_NAME, help=f"project name (default: {PROJECT_NAME!r})")
    parser.add_argument("--url", default=os.environ.get("CVAT_URL") or "http://localhost:8080")
    return parser.parse_args()


def label_request(name, label_type, color):
    return models.PatchedLabelRequest(name=name, type=label_type, color=color, attributes=[])


def main():
    args = parse_args()
    user = os.environ.get("CVAT_USER") or input("CVAT username: ")
    password = os.environ.get("CVAT_PASSWORD") or getpass.getpass("CVAT password: ")

    with make_client(args.url, credentials=(user, password)) as client:
        project = next((p for p in client.projects.list() if p.name == args.name), None)

        if project is None:
            project = client.projects.create(
                models.ProjectWriteRequest(name=args.name, labels=[label_request(*label) for label in LABELS])
            )
            print(f"Created project #{project.id} '{project.name}' with labels: {', '.join(n for n, _, _ in LABELS)}")
        else:
            existing = {label.name.lower(): label.name for label in project.get_labels()}
            missing = [label for label in LABELS if label[0].lower() not in existing]
            for name, _, _ in LABELS:
                if name.lower() in existing and existing[name.lower()] != name:
                    print(f"Note: project already has '{existing[name.lower()]}' (expected '{name}'); left as it is")
            if missing:
                project.update(models.PatchedProjectWriteRequest(labels=[label_request(*label) for label in missing]))
                print(f"Added to project #{project.id} '{project.name}': {', '.join(n for n, _, _ in missing)}")
            else:
                print(f"Project #{project.id} '{project.name}' already has all labels; nothing to change")

        print(f"\nProject page: {args.url.rstrip('/')}/projects/{project.id}")
        print("Create new video tasks from inside this project so they get these labels.")
        print("To add an existing task: open the task, Actions -> Move to project, and map its old labels.")


if __name__ == "__main__":
    main()
