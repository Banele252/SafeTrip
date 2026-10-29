# Raspberry Pi scene detector

Two scripts that run on the Pi:

- `detector.py` looks through the camera every few seconds, detects objects with MobileNet-SSD (OpenCV DNN, CPU only), and writes a plain-text description such as `2 people (1 left, 1 center, near), 1 car (right, far)` to `outbox.jsonl`.
- `uploader.py` reads `outbox.jsonl`, adds the device location, and POSTs each record to the API. It resumes where it left off if the network is down.

## Setup

```bash
cd backend/raspberry_pi
python3 -m venv .venv --system-site-packages   # keeps apt-installed picamera2 visible
source .venv/bin/activate
pip install -r requirements.txt
sudo apt install python3-picamera2             # Pi camera module only
```

Put the two model files in `models/`:

- `MobileNetSSD_deploy.prototxt`
- `MobileNetSSD_deploy.caffemodel`

Both come from the MobileNet-SSD Caffe release (the one used in the OpenCV `object_detection` examples).

## Run

```bash
export API_URL=https://your-api.example.com/detections
export API_KEY=change-me
export DEVICE_ID=pi5-kitchen

python detector.py --source picam        # or --source 0 for a USB webcam
python uploader.py
```

Run each in its own terminal, or as two systemd services.

Useful flags:

- `--once` runs a single cycle and exits (handy for testing).
- `--dry-run` on `uploader.py` prints payloads without sending.
- `--interval` sets seconds between detection cycles (detector) or outbox passes (uploader).

## Location

`uploader.py` tries these in order and attaches the first one it finds:

1. A local `gpsd` daemon (USB GPS receiver), on port 2947.
2. `DEVICE_LAT` and `DEVICE_LON` environment variables.
3. IP geolocation via ipinfo.io (city-level accuracy only).

## Payload sent to the API

```json
{
  "device_id": "pi5-kitchen",
  "timestamp": "2026-10-29T12:00:00+00:00",
  "description": "2 people (1 left, 1 center, near)",
  "objects": [
    {"label": "person", "confidence": 0.91, "position": "left", "proximity": "near"}
  ],
  "location": {"lat": -26.2, "lon": 28.0, "source": "gps"}
}
```

The records are authenticated with an `X-API-Key` header. The API that stores them in MongoDB is not built yet.

## Performance notes

- Pi 5 (8 GB) handles this comfortably at the default 2-second interval.
- On a Pi 4 (2 GB), keep the interval at 2 seconds or higher and run only one detector process.
