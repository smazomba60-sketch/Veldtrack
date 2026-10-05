#!/usr/bin/env python3
"""Veldtrack acceptance loop: deterministic, unattended, CI-friendly."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from veldtrack.device import DeviceConfig, SimulatedTransport, VeldtrackDevice


def run(iterations: int = 100) -> dict:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    checks = {"iterations": iterations, "passed": 0, "failures": []}
    for i in range(iterations):
        now = start + timedelta(seconds=i * 30)
        transport = SimulatedTransport()
        device = VeldtrackDevice(f"cow-{i % 10:03d}", transport)
        device.feed_sensors(80 - (i % 3), bool(i % 2))
        device.feed_gps(now, -29.6100 + i * 0.00001, 30.3900 + i * 0.00001, True)
        result = device.tick(now)
        if result != "sent" or len(transport.sent) != 1:
            checks["failures"].append({"case": i, "stage": "nominal", "result": result})
            continue
        payload = transport.sent[0]
        required = {"device_id", "sequence", "timestamp", "latitude", "longitude", "battery_pct", "motion", "gps_fix", "reason"}
        if set(payload) != required or not payload["gps_fix"] or not (-90 <= payload["latitude"] <= 90) or not (-180 <= payload["longitude"] <= 180):
            checks["failures"].append({"case": i, "stage": "payload_contract", "payload": payload})
            continue

        # Negative path: stale fixes must never be emitted.
        stale = VeldtrackDevice("stale", SimulatedTransport())
        stale.feed_sensors(80, False)
        stale.feed_gps(now - timedelta(minutes=3), payload["latitude"], payload["longitude"], True)
        if stale.tick(now) != "blocked_stale_fix":
            checks["failures"].append({"case": i, "stage": "stale_fix"})
            continue

        # Recovery path: two transport failures must be recovered within the retry budget.
        retry_transport = SimulatedTransport(fail_next=2)
        retry = VeldtrackDevice("retry", retry_transport)
        retry.feed_sensors(80, True)
        retry.feed_gps(now, payload["latitude"], payload["longitude"], True)
        if retry.tick(now) != "sent" or retry.sequence != 1:
            checks["failures"].append({"case": i, "stage": "retry"})
            continue
        checks["passed"] += 1
    checks["ok"] = not checks["failures"] and checks["passed"] == iterations
    return checks


if __name__ == "__main__":
    result = run(int(sys.argv[1]) if len(sys.argv) > 1 else 100)
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(0 if result["ok"] else 1)
