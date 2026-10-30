# SafeTrip

SafeTrip is a Raspberry Pi based safety monitor. A camera on the Pi describes what it sees, a gas sensor watches for smoke, and every event is sent to an API together with the device's location. A small dashboard served from the Pi shows what is being recorded and transmitted.

> **Status:** the Raspberry Pi side is written and tested with mock data. The API that stores events in MongoDB is not built yet. The Terraform in `infrastructure/` creates the GitHub repository.

## How it works

```
 Camera ──► detector.py ──► outbox.jsonl ──► uploader.py ──► API ──► MongoDB
              │    ▲                             │
              │    └── smoke_detector.py         │ uploader_status.json
              ▼                                  ▼
        latest.jpg ──────────────────────► dashboard.py ──► browser (frontend/)
```

1. **Detect.** `detector.py` runs a light MobileNet-SSD model (OpenCV, CPU only) every few seconds. It turns the detections into a sentence such as *"2 people (1 left, 1 center, near)"* and saves an annotated snapshot.
2. **Sense smoke.** `smoke_detector.py` reads an MQ-2 gas sensor through an MCP3008 ADC. It sets a baseline from clean air and records alarm and clear events.
3. **Queue.** Both write to `outbox.jsonl`, one JSON record per line. Nothing is lost if the network is down.
4. **Transmit.** `uploader.py` adds the device location (GPS, configured coordinates, or IP fallback) and POSTs each record to the API. It remembers its position in the file, retries with backoff, and writes a status summary.
5. **Show.** `dashboard.py` serves `frontend/` and a read-only JSON API. It shows the latest snapshot, the current description, pending and sent counts, the location, and any upload error. It never opens the camera.

## Repository layout

| Path | What it is |
| --- | --- |
| `backend/raspberry_pi/` | Scripts that run on the Raspberry Pi: detector, smoke detector, uploader and dashboard server. See its [README](backend/raspberry_pi/README.md) for setup. |
| `frontend/` | Plain HTML, CSS and JavaScript for the Pi dashboard. No build step. |
| `infrastructure/` | Terraform that creates this GitHub repository. See its [README](infrastructure/README.md). |
| `main.py` | Placeholder entry point from project setup. The Pi scripts are run directly. |
| `pyproject.toml`, `uv.lock` | Python project definition and locked dependencies, managed with [uv](https://docs.astral.sh/uv/). |

## Getting started

Python 3.13 is required (see `.python-version`).

```bash
uv sync                     # install the locked dependencies into .venv
```

On the Raspberry Pi, follow [backend/raspberry_pi/README.md](backend/raspberry_pi/README.md). It covers the camera, the model files, environment variables, the dashboard, and running the scripts as services.

## Hardware

- Raspberry Pi 5 (8 GB) is the target. A Pi 4 (2 GB) also works with a longer detection interval.
- Pi camera module or a USB webcam.
- MQ-2 gas sensor with an MCP3008 ADC over SPI, for smoke detection.
- Optional USB GPS receiver (served through gpsd) for location.

## Configuration

Settings are read from environment variables, which can be kept in a `.env` file on the Pi (it is gitignored). The most important ones:

| Variable | Used by | Purpose |
| --- | --- | --- |
| `API_URL`, `API_KEY` | uploader | Where to send events and the key to send with them |
| `DEVICE_ID` | detector | Identifies this Pi in the records |
| `DEVICE_LAT`, `DEVICE_LON` | uploader | Fixed location if there is no GPS |
| `DASHBOARD_TOKEN` | dashboard | Access token for the dashboard and snapshot |

## Security notes

- Never commit `.env` files, API keys, Terraform state, or `*.tfvars` files. They are gitignored, but check before you push.
- The dashboard is for the local network only. Set `DASHBOARD_TOKEN` if other people share that network.
- The repository is public. Keep personal or location data out of committed files.

## Roadmap

- Build the API that receives events and stores them in MongoDB.
- Add authentication and a per-device key to the API.
- Add live video streaming to the dashboard if needed.

## License

Not yet chosen.
