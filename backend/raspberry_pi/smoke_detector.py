"""Detect smoke with an MQ-2 gas sensor and record alarms to the outbox.

The MQ-2 gives an analog voltage that rises as smoke or combustible gas
increases. The Pi has no analog input, so the sensor goes through an MCP3008
ADC on SPI. On startup the script waits for the sensor to warm up, averages
clean-air readings to find the baseline, then raises an alarm when the level
climbs well above it. Alarm and clear events are written to outbox.jsonl in
the same format as detector.py, so uploader.py ships them to the API.

Wiring (MCP3008 on SPI0, sensor on channel 0 by default):
  MQ-2 VCC -> 5V, GND -> GND
  MQ-2 AOUT -> voltage divider (e.g. 10k + 10k) -> MCP3008 CH0
    The divider keeps the 5V sensor output under the Pi's 3.3V limit.
  MCP3008 VDD and VREF -> 3.3V, AGND and DGND -> GND
  MCP3008 CLK, DOUT, DIN, CS -> GPIO11, GPIO9, GPIO10, GPIO8 (CE0)

The MQ-2 DO pin is not used. Its threshold is set by a potentiometer and is
hard to tune, so the baseline comparison here is used instead.
"""

import argparse
import json
import os
import time
import uuid
from collections import deque
from datetime import datetime, timezone

# Sensor levels are 0.0 to 1.0, a fraction of the ADC reference voltage.


def open_sensor(channel):
    from gpiozero import MCP3008

    return MCP3008(channel=channel)


def calibrate(sensor, warmup, seconds, interval=0.5):
    """Wait for the sensor to warm up, then average readings in clean air. Returns the baseline."""
    print(f"Warming up for {warmup:.0f}s, then calibrating for {seconds:.0f}s in clean air")
    time.sleep(warmup)

    readings = []
    end = time.time() + seconds
    while time.time() < end:
        readings.append(sensor.value)
        time.sleep(interval)
    return sum(readings) / len(readings)


def is_alarm(level, baseline, threshold, hysteresis, alarmed):
    """Alarm when the level rises above baseline + threshold.

    Once alarmed, it only clears after falling below baseline + threshold - hysteresis,
    so a reading that hovers near the line doesn't flap between alarm and clear.
    """
    if alarmed:
        return level > baseline + threshold - hysteresis
    return level > baseline + threshold


def build_record(device_id, description):
    return {
        "id": str(uuid.uuid4()),
        "device_id": device_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "description": description,
        "objects": [],
    }


def append_to_outbox(outbox_path, record):
    with open(outbox_path, "a", encoding="utf-8") as outbox:
        outbox.write(json.dumps(record) + "\n")


def parse_args():
    parser = argparse.ArgumentParser(description="Detect smoke with an MQ-2 sensor.")
    parser.add_argument("--channel", type=int, default=int(os.getenv("SMOKE_CHANNEL", "0")),
                        help="MCP3008 channel the MQ-2 output is wired to")
    parser.add_argument("--outbox", default=os.getenv("OUTBOX_PATH", "outbox.jsonl"))
    parser.add_argument("--device-id", default=os.getenv("DEVICE_ID", "raspberry-pi-1"))
    parser.add_argument("--interval", type=float, default=float(os.getenv("SMOKE_INTERVAL", "1")),
                        help="seconds between readings")
    parser.add_argument("--warmup", type=float, default=float(os.getenv("SMOKE_WARMUP", "60")),
                        help="seconds to wait for the MQ-2 to warm up before calibrating")
    parser.add_argument("--calibrate", type=float, default=float(os.getenv("SMOKE_CALIBRATE", "10")),
                        help="seconds of clean-air readings used to set the baseline")
    parser.add_argument("--threshold", type=float, default=float(os.getenv("SMOKE_THRESHOLD", "0.15")),
                        help="rise above the baseline (0.0 to 1.0) that triggers an alarm")
    parser.add_argument("--hysteresis", type=float, default=float(os.getenv("SMOKE_HYSTERESIS", "0.05")),
                        help="how far the level must drop below the alarm line before clearing")
    parser.add_argument("--samples", type=int, default=int(os.getenv("SMOKE_SAMPLES", "5")),
                        help="readings averaged together to smooth out noise")
    parser.add_argument("--once", action="store_true", help="take one reading and exit")
    return parser.parse_args()


def main():
    args = parse_args()
    sensor = open_sensor(args.channel)
    alarmed = False

    try:
        baseline = calibrate(sensor, args.warmup, args.calibrate)
        print(f"Baseline {baseline:.3f}; alarm above {baseline + args.threshold:.3f}")

        window = deque(maxlen=args.samples)
        while True:
            window.append(sensor.value)
            level = sum(window) / len(window)
            print(f"Gas level {level:.3f}")

            now_alarmed = is_alarm(level, baseline, args.threshold, args.hysteresis, alarmed)
            if now_alarmed != alarmed:
                alarmed = now_alarmed
                if alarmed:
                    description = f"Smoke detected (gas level {level:.2f}, baseline {baseline:.2f})"
                else:
                    description = f"Smoke cleared (gas level {level:.2f}, baseline {baseline:.2f})"
                print(description)
                append_to_outbox(args.outbox, build_record(args.device_id, description))

            if args.once:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("Stopping smoke detector")
    finally:
        sensor.close()


if __name__ == "__main__":
    main()
