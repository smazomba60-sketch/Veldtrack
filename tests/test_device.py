from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from veldtrack.device import DeviceConfig, SimulatedTransport, VeldtrackDevice


T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


class DeviceContractTests(unittest.TestCase):
    def make_device(self, **kwargs):
        transport = SimulatedTransport()
        device = VeldtrackDevice("cow-001", transport, DeviceConfig(**kwargs))
        device.feed_sensors(80, True)
        return device, transport

    def test_no_fix_never_emits(self):
        device, transport = self.make_device()
        self.assertEqual(device.tick(T0), "blocked_no_fix")
        self.assertEqual(transport.sent, [])

    def test_valid_fix_emits_schema_valid_telemetry(self):
        device, transport = self.make_device()
        device.feed_gps(T0, -29.6100, 30.3900, True)
        self.assertEqual(device.tick(T0), "sent")
        payload = transport.sent[0]
        self.assertEqual(set(payload), {"device_id", "sequence", "timestamp", "latitude", "longitude", "battery_pct", "motion", "gps_fix", "reason"})
        self.assertEqual(payload["sequence"], 0)
        self.assertTrue(payload["gps_fix"])

    def test_stale_fix_is_blocked(self):
        device, transport = self.make_device()
        device.feed_gps(T0, -29.61, 30.39, True)
        self.assertEqual(device.tick(T0), "sent")
        self.assertEqual(device.tick(T0 + timedelta(minutes=3)), "blocked_stale_fix")
        self.assertEqual(len(transport.sent), 1)

    def test_low_battery_is_immediate_alert(self):
        device, transport = self.make_device(report_interval=timedelta(hours=1))
        device.feed_gps(T0, -29.61, 30.39, True)
        self.assertEqual(device.tick(T0), "sent")
        device.feed_sensors(10, False)
        self.assertEqual(device.tick(T0 + timedelta(minutes=1)), "sent")
        self.assertEqual(transport.sent[-1]["reason"], "low_battery")

    def test_retries_are_bounded_and_sequence_advances_once(self):
        device, transport = self.make_device()
        device.feed_gps(T0, -29.61, 30.39, True)
        transport.fail_next = 2
        self.assertEqual(device.tick(T0), "sent")
        self.assertEqual(len(transport.sent), 1)
        self.assertEqual(device.sequence, 1)

        transport.fail_next = 4
        device.feed_gps(T0 + timedelta(minutes=5), -29.61, 30.39, True)
        self.assertEqual(device.tick(T0 + timedelta(minutes=5)), "send_failed")
        self.assertEqual(device.sequence, 1)
        self.assertEqual(len(transport.sent), 1)

    def test_watchdog_recovers_from_stalled_loop(self):
        device, _ = self.make_device()
        device.feed_gps(T0, -29.61, 30.39, True)
        device.tick(T0)
        self.assertTrue(device.watchdog_check(T0 + timedelta(minutes=11)))
        self.assertEqual(device.watchdog_resets, 1)


if __name__ == "__main__":
    unittest.main()
