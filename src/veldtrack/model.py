from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any


def utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class Telemetry:
    device_id: str
    sequence: int
    timestamp: datetime
    latitude: float
    longitude: float
    battery_pct: float
    motion: bool
    gps_fix: bool
    reason: str

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.device_id or len(self.device_id) > 64:
            errors.append("device_id must be 1..64 characters")
        if self.sequence < 0:
            errors.append("sequence must be non-negative")
        if self.timestamp.tzinfo is None:
            errors.append("timestamp must be timezone-aware")
        if not (-90 <= self.latitude <= 90) or not isfinite(self.latitude):
            errors.append("latitude out of range")
        if not (-180 <= self.longitude <= 180) or not isfinite(self.longitude):
            errors.append("longitude out of range")
        if not (0 <= self.battery_pct <= 100) or not isfinite(self.battery_pct):
            errors.append("battery_pct out of range")
        if not self.gps_fix:
            errors.append("telemetry must not be emitted without a GPS fix")
        if not self.reason:
            errors.append("reason is required")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "sequence": self.sequence,
            "timestamp": utc_iso(self.timestamp),
            "latitude": round(self.latitude, 7),
            "longitude": round(self.longitude, 7),
            "battery_pct": round(self.battery_pct, 2),
            "motion": self.motion,
            "gps_fix": self.gps_fix,
            "reason": self.reason,
        }
