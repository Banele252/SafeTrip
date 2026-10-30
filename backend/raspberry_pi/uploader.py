"""Send detection records from the outbox to the API, together with the device location.

Reads lines appended by detector.py, POSTs each one, and remembers how far it
got in a separate offset file so nothing is sent twice and nothing is lost if
the network is down. After each pass it writes a status file for the dashboard.
"""

import argparse
import json
import os
import socket
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

GPSD_HOST = "127.0.0.1"
GPSD_PORT = 2947
LOCATION_TTL = 300  # seconds before the location is looked up again


def location_from_gpsd(timeout=3):
    """Read the latest fix from a local gpsd daemon (e.g. a USB GPS receiver)."""
    try:
        with socket.create_connection((GPSD_HOST, GPSD_PORT), timeout=timeout) as sock:
            sock.sendall(b'?WATCH={"enable":true,"json":true}\n')
            reader = sock.makefile("r")
            for _ in range(20):
                message = json.loads(reader.readline())
                if message.get("class") == "TPV" and "lat" in message and "lon" in message:
                    return {"lat": message["lat"], "lon": message["lon"], "source": "gps"}
    except (OSError, ValueError):
        pass
    return None


def location_from_env():
    lat, lon = os.getenv("DEVICE_LAT"), os.getenv("DEVICE_LON")
    if lat and lon:
        return {"lat": float(lat), "lon": float(lon), "source": "configured"}
    return None


def location_from_ip(timeout=5):
    """Approximate location from the public IP. Last resort, only city-level accurate."""
    try:
        response = requests.get("https://ipinfo.io/json", timeout=timeout)
        response.raise_for_status()
        lat, lon = response.json()["loc"].split(",")
        return {"lat": float(lat), "lon": float(lon), "source": "ip"}
    except (requests.RequestException, KeyError, ValueError):
        return None


def get_location():
    return location_from_gpsd() or location_from_env() or location_from_ip()


def read_offset(offset_path):
    try:
        with open(offset_path, "r", encoding="utf-8") as offset_file:
            return int(offset_file.read().strip() or 0)
    except (FileNotFoundError, ValueError):
        return 0


def write_offset(offset_path, offset):
    with open(offset_path, "w", encoding="utf-8") as offset_file:
        offset_file.write(str(offset))


def count_pending(outbox_path, offset):
    """Number of complete outbox lines that have not been sent yet."""
    if not os.path.exists(outbox_path):
        return 0
    with open(outbox_path, "rb") as outbox:
        outbox.seek(offset)
        return sum(1 for line in outbox if line.endswith(b"\n"))


def next_complete_line(outbox_path, offset):
    """Return (line, new_offset) for the next complete line, or (None, offset) if none is ready."""
    if not os.path.exists(outbox_path):
        return None, offset
    with open(outbox_path, "rb") as outbox:
        outbox.seek(offset)
        line = outbox.readline()
    # A line without a trailing newline is still being written; leave it for next time.
    if not line.endswith(b"\n"):
        return None, offset
    return line.decode("utf-8"), offset + len(line)


def post_with_retries(api_url, api_key, payload, attempts=3):
    """Return None on success, otherwise a short description of the last error."""
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key

    error = "unknown error"
    delay = 2
    for attempt in range(1, attempts + 1):
        try:
            response = requests.post(api_url, json=payload, headers=headers, timeout=10)
            if response.status_code < 300:
                return None
            error = f"API returned {response.status_code}"
            print(f"{error}: {response.text[:200]}")
        except requests.RequestException as exc:
            error = f"request failed: {exc.__class__.__name__}"
            print(f"Request failed: {exc}")

        if attempt < attempts:
            time.sleep(delay)
            delay *= 2
    return error


def build_payload(record, location):
    return {
        "device_id": record["device_id"],
        "timestamp": record["timestamp"],
        "description": record["description"],
        "objects": record["objects"],
        "location": location,
    }


def send_pending(args, location):
    """Send every complete outbox line after the saved offset.

    Returns (sent_count, error). Stops at the first failure to keep order.
    """
    offset = read_offset(args.offset_file)
    sent = 0

    while True:
        line, next_offset = next_complete_line(args.outbox, offset)
        if line is None:
            break

        record = json.loads(line)
        payload = build_payload(record, location)

        if args.dry_run:
            print(json.dumps(payload, indent=2))
        else:
            error = post_with_retries(args.api_url, args.api_key, payload)
            if error:
                print("Giving up for now; will retry on the next pass")
                return sent, error

        offset = next_offset
        if not args.dry_run:
            write_offset(args.offset_file, offset)
        sent += 1

    return sent, None


def read_status(status_path):
    try:
        with open(status_path, "r", encoding="utf-8") as status_file:
            return json.load(status_file)
    except (FileNotFoundError, ValueError):
        return {}


def write_status(status_path, status):
    """Write to a temp file and rename, so the dashboard never reads a half-written file."""
    temp_path = status_path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as status_file:
        json.dump(status, status_file)
    os.replace(temp_path, status_path)


def build_status(previous, args, location, sent, error):
    """Summary of the last pass for the dashboard. Never includes the API key."""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "state": "error" if error else "ok",
        "last_success": now if sent and not error else previous.get("last_success"),
        "last_error": error,
        "pending": count_pending(args.outbox, read_offset(args.offset_file)),
        "sent_total": previous.get("sent_total", 0) + sent,
        "location": location,
        "api_host": urlparse(args.api_url).netloc,
        "updated_at": now,
    }


def parse_args():
    parser = argparse.ArgumentParser(description="Upload detections to the SafeTrip API.")
    parser.add_argument("--outbox", default=os.getenv("OUTBOX_PATH", "outbox.jsonl"))
    parser.add_argument("--offset-file", default=os.getenv("OFFSET_PATH", "outbox.offset"))
    parser.add_argument("--status-file", default=os.getenv("STATUS_PATH", "uploader_status.json"),
                        help="where to write the status summary the dashboard reads")
    parser.add_argument("--api-url", default=os.getenv("API_URL", "http://localhost:8000/detections"))
    parser.add_argument("--api-key", default=os.getenv("API_KEY", ""))
    parser.add_argument("--interval", type=float, default=float(os.getenv("UPLOAD_INTERVAL", "10")),
                        help="seconds between passes over the outbox")
    parser.add_argument("--once", action="store_true", help="run one pass and exit")
    parser.add_argument("--dry-run", action="store_true", help="print payloads without sending them")
    return parser.parse_args()


def main():
    args = parse_args()
    status = read_status(args.status_file)
    location, located_at = None, 0.0

    try:
        while True:
            if location is None or time.time() - located_at > LOCATION_TTL:
                location = get_location()
                located_at = time.time()
            if location is None:
                print("No location available; sending without it")

            sent, error = send_pending(args, location)
            if sent:
                print(f"Processed {sent} record(s)")
            if error:
                print(f"Last error: {error}")

            if not args.dry_run:
                status = build_status(status, args, location, sent, error)
                write_status(args.status_file, status)

            if args.once:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("Stopping uploader")


if __name__ == "__main__":
    main()
