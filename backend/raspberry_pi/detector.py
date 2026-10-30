"""Detect objects in the camera feed and describe the scene in plain text.

Uses OpenCV's DNN module with a MobileNet-SSD (Caffe) model, which runs on the
CPU and is light enough for a Raspberry Pi. Each detection cycle appends one
JSON line to an outbox file; uploader.py ships those lines to the API.
"""

import argparse
import json
import os
import time
import uuid
from datetime import datetime, timezone

import cv2
import numpy as np

# Class labels the MobileNet-SSD (VOC) model was trained on, in model order.
CLASSES = [
    "background", "aeroplane", "bicycle", "bird", "boat", "bottle", "bus",
    "car", "cat", "chair", "cow", "diningtable", "dog", "horse", "motorbike",
    "person", "pottedplant", "sheep", "sofa", "train", "tvmonitor",
]

INPUT_SIZE = (300, 300)


def load_net(model_dir):
    prototxt = os.path.join(model_dir, "MobileNetSSD_deploy.prototxt")
    caffemodel = os.path.join(model_dir, "MobileNetSSD_deploy.caffemodel")
    return cv2.dnn.readNetFromCaffe(prototxt, caffemodel)


def open_camera(source):
    """Use the Pi camera module when asked for, otherwise a V4L2/USB camera."""
    if source == "picam":
        from picamera2 import Picamera2

        cam = Picamera2()
        cam.configure(cam.create_video_configuration(main={"size": (640, 480), "format": "BGR888"}))
        cam.start()
        return cam
    return cv2.VideoCapture(int(source))


def read_frame(cam):
    if isinstance(cam, cv2.VideoCapture):
        ok, frame = cam.read()
        return frame if ok else None
    return cam.capture_array()


def close_camera(cam):
    if isinstance(cam, cv2.VideoCapture):
        cam.release()
    else:
        cam.stop()


def detect(net, frame, confidence_threshold):
    """Return a list of detected objects for one frame."""
    height, width = frame.shape[:2]
    blob = cv2.dnn.blobFromImage(frame, 0.007843, INPUT_SIZE, 127.5)
    net.setInput(blob)
    output = net.forward()

    objects = []
    for i in range(output.shape[2]):
        confidence = float(output[0, 0, i, 2])
        if confidence < confidence_threshold:
            continue

        class_id = int(output[0, 0, i, 1])
        if class_id >= len(CLASSES) or CLASSES[class_id] == "background":
            continue

        x1, y1, x2, y2 = output[0, 0, i, 3:7] * np.array([width, height, width, height])
        box_w, box_h = x2 - x1, y2 - y1
        x_center = (x1 + x2) / 2 / width
        area_ratio = (box_w * box_h) / (width * height)

        objects.append({
            "label": CLASSES[class_id],
            "confidence": round(confidence, 3),
            "position": position_of(x_center),
            "proximity": proximity_of(area_ratio),
            "box": (int(x1), int(y1), int(x2), int(y2)),
        })
    return objects


def position_of(x_center):
    if x_center < 1 / 3:
        return "left"
    if x_center > 2 / 3:
        return "right"
    return "center"


def proximity_of(area_ratio):
    if area_ratio > 0.25:
        return "near"
    if area_ratio > 0.08:
        return "medium"
    return "far"


def describe(objects):
    """Turn detections into a short sentence, e.g. '2 people (1 left, 1 center, near), 1 car (right, far)'."""
    if not objects:
        return "No notable objects detected"

    groups = {}
    for obj in objects:
        groups.setdefault(obj["label"], []).append(obj)

    parts = []
    for label, items in groups.items():
        count = len(items)
        name = label
        if label == "person":
            name = "person" if count == 1 else "people"
        elif count > 1:
            name = f"{label}s"

        positions = {}
        for item in items:
            positions[item["position"]] = positions.get(item["position"], 0) + 1
        position_text = ", ".join(f"{n} {pos}" for pos, n in positions.items())

        nearest = min(items, key=lambda item: ["near", "medium", "far"].index(item["proximity"]))
        parts.append(f"{count} {name} ({position_text}, {nearest['proximity']})")

    return ", ".join(parts)


def save_snapshot(frame, objects, snapshot_path):
    """Save the frame with boxes drawn on it. Written to a temp file first so readers never see a partial image."""
    annotated = frame.copy()
    for obj in objects:
        x1, y1, x2, y2 = obj["box"]
        cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(annotated, obj["label"], (x1, max(y1 - 6, 12)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

    temp_path = snapshot_path + ".tmp.jpg"
    cv2.imwrite(temp_path, annotated)
    os.replace(temp_path, snapshot_path)


def build_record(device_id, objects, description):
    # Boxes are only for the snapshot, so leave them out of what goes to the API.
    api_objects = [{key: value for key, value in obj.items() if key != "box"} for obj in objects]
    return {
        "id": str(uuid.uuid4()),
        "device_id": device_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "description": description,
        "objects": api_objects,
    }


def append_to_outbox(outbox_path, record):
    with open(outbox_path, "a", encoding="utf-8") as outbox:
        outbox.write(json.dumps(record) + "\n")


def run_cycle(net, cam, args, last_description):
    frame = read_frame(cam)
    if frame is None:
        print("Could not read a frame from the camera")
        return last_description

    objects = detect(net, frame, args.confidence)
    description = describe(objects)
    print(description)

    save_snapshot(frame, objects, args.snapshot)

    # Only record when the scene changed, so the uploader doesn't resend the same thing.
    if description != last_description:
        append_to_outbox(args.outbox, build_record(args.device_id, objects, description))
    return description


def parse_args():
    parser = argparse.ArgumentParser(description="Describe what the camera sees.")
    parser.add_argument("--source", default=os.getenv("CAMERA_SOURCE", "picam"),
                        help="'picam' for the Pi camera module, or a camera index such as 0 for USB")
    parser.add_argument("--model-dir", default=os.getenv("MODEL_DIR", "models"),
                        help="folder with MobileNetSSD_deploy.prototxt and .caffemodel")
    parser.add_argument("--outbox", default=os.getenv("OUTBOX_PATH", "outbox.jsonl"))
    parser.add_argument("--snapshot", default=os.getenv("SNAPSHOT_PATH", "latest.jpg"),
                        help="where to save the latest annotated frame for the dashboard")
    parser.add_argument("--device-id", default=os.getenv("DEVICE_ID", "raspberry-pi-1"))
    parser.add_argument("--interval", type=float, default=float(os.getenv("DETECT_INTERVAL", "2")),
                        help="seconds between detection cycles")
    parser.add_argument("--confidence", type=float, default=float(os.getenv("CONFIDENCE", "0.5")))
    parser.add_argument("--once", action="store_true", help="run one cycle and exit")
    return parser.parse_args()


def main():
    args = parse_args()
    net = load_net(args.model_dir)
    cam = open_camera(args.source)
    last_description = None

    try:
        while True:
            last_description = run_cycle(net, cam, args, last_description)
            if args.once:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("Stopping detector")
    finally:
        close_camera(cam)


if __name__ == "__main__":
    main()
