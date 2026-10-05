from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

from .model import Telemetry


class Transport(Protocol):
    def send(self, payload: dict) -> bool: ...


@dataclass
class SimulatedTransport:
    fail_next: int = 0
    sent: list[dict] | None = None

    def __post_init__(self) -> None:
        self.sent = [] if self.sent is None else self.sent

    def send(self, payload: dict) -> bool:
        if self.fail_next:
            self.fail_next -= 1
            return False
        self.sent.append(payload)
        return True


@dataclass
class DeviceConfig:
    report_interval: timedelta = timedelta(minutes=5)
    max_retries: int = 3
    low_battery_pct: float = 15.0
    gps_stale_after: timedelta = timedelta(minutes=2)


class VeldtrackDevice:
    """Hardware-independent device core.

    A board adapter should provide real GNSS, motion, battery and transport
    readings and call ``tick``. The core owns safety-critical invariants:
    never publish an invalid/stale fix, monotonic sequence numbers, bounded
    retries, and recovery after a stalled tick loop.
    """

    def __init__(self, device_id: str, transport: Transport, config: DeviceConfig | None = None):
        self.device_id = device_id
        self.transport = transport
        self.config = config or DeviceConfig()
        self.sequence = 0
        self.last_report_at: datetime | None = None
        self.last_fix_at: datetime | None = None
        self.latitude = 0.0
        self.longitude = 0.0
        self.battery_pct = 0.0
        self.motion = False
        self.gps_fix = False
        self.watchdog_resets = 0
        self._last_tick_at: datetime | None = None

    def feed_gps(self, now: datetime, latitude: float, longitude: float, fix: bool) -> None:
        self.latitude, self.longitude, self.gps_fix = latitude, longitude, fix
        if fix:
            self.last_fix_at = now

    def feed_sensors(self, battery_pct: float, motion: bool) -> None:
        self.battery_pct, self.motion = battery_pct, motion

    def watchdog_check(self, now: datetime, max_tick_gap: timedelta = timedelta(minutes=10)) -> bool:
        if self._last_tick_at and now - self._last_tick_at > max_tick_gap:
            self.watchdog_resets += 1
            self._last_tick_at = now
            self.last_report_at = None
            return True
        return False

    def tick(self, now: datetime) -> str:
        self.watchdog_check(now)
        self._last_tick_at = now
        if not self.gps_fix or self.last_fix_at is None:
            return "blocked_no_fix"
        if now - self.last_fix_at > self.config.gps_stale_after:
            return "blocked_stale_fix"
        due = self.last_report_at is None or now - self.last_report_at >= self.config.report_interval
        low_battery = self.battery_pct <= self.config.low_battery_pct
        if not due and not low_battery:
            return "not_due"
        reason = "low_battery" if low_battery else "periodic"
        telemetry = Telemetry(
            device_id=self.device_id,
            sequence=self.sequence,
            timestamp=now,
            latitude=self.latitude,
            longitude=self.longitude,
            battery_pct=self.battery_pct,
            motion=self.motion,
            gps_fix=self.gps_fix,
            reason=reason,
        )
        errors = telemetry.validate()
        if errors:
            return "blocked_invalid:" + ",".join(errors)
        payload = telemetry.to_dict()
        for _attempt in range(self.config.max_retries + 1):
            if self.transport.send(payload):
                self.sequence += 1
                self.last_report_at = now
                return "sent"
        return "send_failed"
