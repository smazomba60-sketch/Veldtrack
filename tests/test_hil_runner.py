from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from hil_runner import SimulatedRig, run_sequence, validate_cycle


class HILRunnerTests(unittest.TestCase):
    def test_simulated_1000_cycle_sequence_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            verdict = run_sequence(SimulatedRig(), 1000, Path(tmp), "test-1000")
            self.assertTrue(verdict["ok"], verdict)
            self.assertEqual(verdict["cycles_completed"], 1000)
            self.assertEqual(verdict["passed"], 1000)
            self.assertTrue((Path(tmp) / "verdict.json").is_file())
            self.assertTrue((Path(tmp) / "dut-events.ndjson").is_file())
            self.assertTrue((Path(tmp) / "radio-uplinks.ndjson").is_file())

    def test_persistent_radio_failure_requires_tx_fail_and_no_ack(self):
        result = validate_cycle(
            3,
            "persistent_radio_failure",
            {
                "events": [
                    {"event": "BOOT"},
                    {"event": "GNSS_STATUS", "fix": True},
                    {"event": "TX_FAIL", "attempts": 4},
                ],
                "uplinks": [],
            },
            expected_sequence=2,
        )
        self.assertTrue(result.ok, result.reason)

    def test_ack_with_wrong_sequence_fails(self):
        result = validate_cycle(
            0,
            "brownout",
            {
                "events": [
                    {"event": "BOOT"},
                    {"event": "GNSS_STATUS", "fix": True},
                    {"event": "WATCHDOG_RESET"},
                    {"event": "TX_ACK"},
                ],
                "uplinks": [{"gps_fix": True, "sequence": 99, "latitude": 0, "longitude": 0}],
            },
            expected_sequence=0,
        )
        self.assertFalse(result.ok)
        self.assertIn("sequence", result.reason)


if __name__ == "__main__":
    unittest.main()
