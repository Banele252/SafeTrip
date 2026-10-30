"""Read-only web dashboard that shows what the Pi is recording and transmitting.

Serves the frontend from ../../frontend and a small JSON API built from the
files detector.py and uploader.py write. It never opens the camera and never
writes to the outbox, so a dashboard bug cannot break detection or uploads.

Set DASHBOARD_TOKEN to require a token for the API and snapshot.
"""

import hmac
import json
import os
from collections import deque

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from uploader import count_pending, read_offset

HERE = os.path.dirname(os.path.abspath(__file__))
OUTBOX_PATH = os.getenv("OUTBOX_PATH", "outbox.jsonl")
OFFSET_PATH = os.getenv("OFFSET_PATH", "outbox.offset")
STATUS_PATH = os.getenv("STATUS_PATH", "uploader_status.json")
SNAPSHOT_PATH = os.getenv("SNAPSHOT_PATH", "latest.jpg")
FRONTEND_DIR = os.getenv("FRONTEND_DIR", os.path.normpath(os.path.join(HERE, "..", "..", "frontend")))
DASHBOARD_TOKEN = os.getenv("DASHBOARD_TOKEN", "")
DASHBOARD_HOST = os.getenv("DASHBOARD_HOST", "0.0.0.0")
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8080"))


def require_token(request: Request):
    if not DASHBOARD_TOKEN:
        return
    supplied = request.query_params.get("token", "")
    authorization = request.headers.get("authorization", "")
    if authorization.startswith("Bearer "):
        supplied = authorization[len("Bearer "):]
    if not hmac.compare_digest(supplied.encode(), DASHBOARD_TOKEN.encode()):
        raise HTTPException(status_code=401, detail="Invalid or missing token")


app = FastAPI(title="SafeTrip Pi dashboard", dependencies=[Depends(require_token)])


def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as json_file:
            return json.load(json_file)
    except (FileNotFoundError, ValueError):
        return {}


def load_recent_records(limit):
    """Last `limit` outbox records, oldest first, each marked as sent or pending.

    A record is sent when its end byte position is at or before the uploader's offset.
    """
    offset = read_offset(OFFSET_PATH)
    recent = deque(maxlen=limit)

    if os.path.exists(OUTBOX_PATH):
        with open(OUTBOX_PATH, "rb") as outbox:
            position = 0
            for line in outbox:
                position += len(line)
                if line.endswith(b"\n"):
                    recent.append((position, line))

    records = []
    for end_position, line in recent:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        record["sent"] = end_position <= offset
        records.append(record)
    return records


@app.get("/api/state")
def state():
    records = load_recent_records(1)
    snapshot_mtime = os.path.getmtime(SNAPSHOT_PATH) if os.path.exists(SNAPSHOT_PATH) else None
    return {
        "latest": records[-1] if records else None,
        "pending": count_pending(OUTBOX_PATH, read_offset(OFFSET_PATH)),
        "status": read_json(STATUS_PATH),
        "snapshot_mtime": snapshot_mtime,
    }


@app.get("/api/detections")
def detections(limit: int = Query(50, ge=1, le=500)):
    # Newest first for the log.
    return list(reversed(load_recent_records(limit)))


@app.get("/latest.jpg")
def latest_snapshot():
    if not os.path.exists(SNAPSHOT_PATH):
        raise HTTPException(status_code=404, detail="No snapshot yet")
    return FileResponse(SNAPSHOT_PATH, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


# Mounted last so the API routes above take priority. Static files hold no data, so they stay open.
if os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")


if __name__ == "__main__":
    if not DASHBOARD_TOKEN:
        print("Warning: DASHBOARD_TOKEN is not set; anyone on the network can see the snapshot")
    uvicorn.run(app, host=DASHBOARD_HOST, port=DASHBOARD_PORT)
