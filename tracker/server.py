"""HTTP service behind the "Track with MedSAM2" item of the CVAT UI plugin.

The browser calls it through CVAT's address (Traefik routes /medsam2-tracker/ here),
so it receives the user's CVAT session cookies and acts as that user.
Runs one tracking job at a time on the GPU; the UI polls run status for progress.

  POST /medsam2-tracker/api/runs        {"job_id", "frame", "start", "stop", "replace"}
  GET  /medsam2-tracker/api/runs        active runs, oldest first (other users' runs without details)
  GET  /medsam2-tracker/api/runs/<id>   {"state", "stage", "percent", "message", ...}
  GET  /medsam2-tracker/api/health      container health check (Traefik skips unhealthy containers)
"""

import json
import logging
import os
import queue
import threading
import time
import traceback
import uuid
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cvat_sdk import Client
from cvat_sdk.api_client.exceptions import ApiException

from medsam2_tracking import TrackingError, load_predictor, track

PREFIX = "/medsam2-tracker/api"
CVAT_URL = os.environ.get("CVAT_INTERNAL_URL", "http://cvat-server:8080")
PORT = int(os.environ.get("PORT", "8000"))
RUN_TTL = 24 * 3600  # forget finished runs after a day

# Share of the progress bar for each stage, in order
STAGES = {
    "Waiting for other tracking runs": (0, 0),
    "Downloading frames": (0, 30),
    "Loading frames into MedSAM2": (30, 32),
    "Tracking": (32, 92),
    "Removing previous tracking results": (92, 94),
    "Uploading masks": (94, 100),
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("medsam2-tracker")

runs = {}
runs_lock = threading.Lock()
work = queue.Queue()


def make_cvat_client(cookies):
    client = Client(CVAT_URL, check_server_version=False)
    client.api_client.cookies["sessionid"] = cookies["sessionid"]
    client.api_client.cookies["csrftoken"] = cookies["csrftoken"]
    # Same as Client.login(): unsafe requests need the CSRF token as a header too
    client.api_client.configuration.api_key["csrfHeaderAuth"] = cookies["csrftoken"]
    return client


def update_run(run_id, **fields):
    with runs_lock:
        runs[run_id].update(fields, updated=time.time())


def worker():
    predictor, device = load_predictor()
    log.info("MedSAM2 loaded on %s", device)

    while True:
        run_id, request = work.get()
        update_run(run_id, state="running")

        def progress(stage, done, total):
            low, high = STAGES.get(stage, (0, 100))
            percent = low + (high - low) * (done / total if total else 1)
            message = f"{stage} ({done}/{total})" if total > 1 else stage
            update_run(run_id, stage=stage, percent=round(percent, 1), message=message)

        try:
            with make_cvat_client(request["cookies"]) as client:
                job = client.jobs.retrieve(request["job_id"])
                key_frame, key_shapes, uploaded = track(
                    job,
                    predictor,
                    start=request["start"],
                    stop=request["stop"],
                    key_frame=request["frame"],
                    replace=request["replace"],
                    progress=progress,
                )
            update_run(
                run_id,
                state="done",
                percent=100,
                stage="Done",
                message=f"Tracked {len(key_shapes)} object(s) from frame {key_frame}: {uploaded} masks added",
            )
        except TrackingError as e:
            update_run(run_id, state="failed", message=str(e))
        except ApiException as e:
            update_run(run_id, state="failed", message=f"CVAT request failed ({e.status}): {e.reason}")
        except Exception as e:
            log.error("Run %s failed:\n%s", run_id, traceback.format_exc())
            update_run(run_id, state="failed", message=f"Tracking failed: {e}")
        finally:
            work.task_done()


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def get_cookies(self):
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        cookies = {name: cookie[name].value for name in ("sessionid", "csrftoken") if name in cookie and cookie[name].value}
        return cookies if len(cookies) == 2 else None

    @staticmethod
    def run_view(run):
        # Call with runs_lock held
        body = {k: v for k, v in run.items() if k != "sessionid"}
        if run["state"] == "queued":
            ahead = sum(1 for r in runs.values() if r["state"] in ("queued", "running") and r["created"] < run["created"])
            body["message"] = f"Waiting for {ahead} other tracking run(s) to finish" if ahead else "Starting..."
        return body

    def do_GET(self):
        if self.path == PREFIX + "/health":
            return self.send_json(200, {"status": "ok"})

        cookies = self.get_cookies()
        if cookies is None:
            return self.send_json(401, {"message": "Not logged in to CVAT"})

        if self.path == PREFIX + "/runs":
            with runs_lock:
                active = sorted(
                    (r for r in runs.values() if r["state"] in ("queued", "running")), key=lambda r: r["created"]
                )
                body = []
                for run in active:
                    if run["sessionid"] == cookies["sessionid"]:
                        body.append(dict(self.run_view(run), mine=True))
                    else:
                        # Other users' runs: only enough to show the queue
                        body.append({k: run[k] for k in ("state", "stage", "percent")} | {"mine": False})
            return self.send_json(200, body)

        if not self.path.startswith(PREFIX + "/runs/"):
            return self.send_json(404, {"message": "Not found"})

        run_id = self.path[len(PREFIX + "/runs/") :]
        with runs_lock:
            run = runs.get(run_id)
            # Only the session that started a run can see it
            if run is None or run["sessionid"] != cookies["sessionid"]:
                return self.send_json(404, {"message": "Unknown tracking run"})
            body = self.run_view(run)
        self.send_json(200, body)

    def do_POST(self):
        if self.path != PREFIX + "/runs":
            return self.send_json(404, {"message": "Not found"})

        cookies = self.get_cookies()
        if cookies is None:
            return self.send_json(401, {"message": "Not logged in to CVAT"})
        # Double-submit check: a page from another site can send the cookies, but cannot read them
        if self.headers.get("X-CSRFToken") != cookies["csrftoken"]:
            return self.send_json(403, {"message": "Missing or invalid CSRF token"})

        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            request = {
                "job_id": int(body["job_id"]),
                "frame": int(body["frame"]),
                "start": int(body["start"]),
                "stop": int(body["stop"]),
                "replace": bool(body.get("replace", False)),
                "cookies": cookies,
            }
        except (ValueError, KeyError, TypeError) as e:
            return self.send_json(400, {"message": f"Invalid request: {e}"})

        # Fail fast if the user cannot open this job, rather than after queueing
        try:
            with make_cvat_client(cookies) as client:
                job = client.jobs.retrieve(request["job_id"])
        except ApiException as e:
            log.warning("CVAT rejected job lookup (%s): %s", e.status, e.body)
            return self.send_json(
                e.status if e.status in (401, 403, 404) else 502,
                {"message": f"CVAT rejected the request ({e.status} {e.reason})"},
            )
        if not job.start_frame <= request["start"] <= request["frame"] <= request["stop"] <= job.stop_frame:
            return self.send_json(
                400,
                {"message": f"Frames must satisfy {job.start_frame} <= start <= key frame <= stop <= {job.stop_frame}"},
            )

        run_id = uuid.uuid4().hex
        now = time.time()
        with runs_lock:
            for old_id in [i for i, r in runs.items() if r["state"] in ("done", "failed") and now - r["updated"] > RUN_TTL]:
                del runs[old_id]
            runs[run_id] = {
                "id": run_id,
                "state": "queued",
                "stage": "Waiting for other tracking runs",
                "percent": 0,
                "message": "Waiting for other tracking runs to finish",
                "job_id": request["job_id"],
                "created": now,
                "updated": now,
                "sessionid": cookies["sessionid"],
            }
        work.put((run_id, request))
        log.info("Queued run %s for job %s, frames %s..%s", run_id, request["job_id"], request["start"], request["stop"])
        self.send_json(202, {"id": run_id})

    def log_message(self, format, *args):
        pass  # the UI polls every second; don't log each request


if __name__ == "__main__":
    threading.Thread(target=worker, daemon=True).start()
    log.info("Listening on port %s, CVAT at %s", PORT, CVAT_URL)
    ThreadingHTTPServer(("", PORT), Handler).serve_forever()
