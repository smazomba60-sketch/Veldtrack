# Veldtrack

A livestock tracking device project with a **hardware-independent telemetry core** and a repeatable acceptance loop. The repository began as a README-only project; this baseline makes the device behavior testable before a specific MCU, GNSS module, radio, or cloud backend is selected.

## What is implemented

- Strict telemetry contract: device ID, monotonic sequence, UTC timestamp, latitude/longitude, battery, motion, fix status, and reason.
- GPS safety gates: no-fix and stale-fix readings are blocked from transmission.
- Bounded transport retries: the sequence advances only after a successful send.
- Low-battery alert path that reports immediately instead of waiting for the periodic interval.
- Watchdog recovery signal for a stalled main loop.
- Deterministic simulator transport for CI and future hardware adapters.

## Run the validation loop

```bash
python -m unittest discover -s tests -v
python scripts/loop_test.py 1000
python scripts/hil_runner.py --mode sim --cycles 1000
```

The loop exercises nominal telemetry, payload/schema invariants, stale-GPS rejection, and recovery after two transport failures. Any failure exits non-zero and prints a JSON failure record, making it suitable for GitHub Actions or a hardware test runner.

The HIL runner rotates brownout, hard-cut, transient-radio-loss, and persistent-radio-failure scenarios. Simulation writes `manifest.json`, `dut-events.ndjson`, `radio-uplinks.ndjson`, and `verdict.json` under `artifacts/hil/<run-id>/`. For real hardware, use `--mode external --rig-command <helper>`; the helper receives one JSON action on stdin and must return one JSON result, as specified in [`scripts/hil_runner.py`](scripts/hil_runner.py).

## Hardware-in-the-loop testing

The [HIL test harness specification](docs/HIL_TEST_HARNESS.md) defines the real-GNSS and real-radio fixtures, DUT observability contract, test matrix, evidence bundle, safety rules, and release gates. It complements—not replaces—the deterministic software loop above.

The [HIL power and fault-injection fixture design](docs/HIL_POWER_FAULT_FIXTURE.md) includes the circuit netlist, rendered schematic, bring-up procedure, fault recipes, and BOM. The machine-readable BOM is available at [HIL_POWER_FAULT_FIXTURE_BOM.csv](docs/HIL_POWER_FAULT_FIXTURE_BOM.csv).

## Hardware integration boundary

A board-specific adapter should feed these readings into `VeldtrackDevice`:

1. Read and checksum-validate complete GNSS sentences; only call `feed_gps(..., fix=True)` when the receiver reports a valid fix.
2. Read the accelerometer/motion sensor and battery gauge; call `feed_sensors(...)`.
3. Call `tick(now)` from the main loop and implement `Transport.send(payload)` using the selected LoRaWAN, LTE-M/NB-IoT, or MQTT stack.
4. Keep the same tests and add a serial/radio hardware-in-the-loop adapter once the board and radio are chosen.

This cannot **guarantee** a physical device is field-functional without the actual schematic, firmware, GNSS/radio modules, enclosure, power system, and field measurements. It does provide a tight, red-capable software acceptance gate and makes those hardware seams explicit.

## GitHub solutions used as design references

- [Open Source Range GPS Collar](https://github.com/Open-Source-Range/OSR_GPS_Collar) — open livestock collar architecture, low-power cycling, GNSS and on-device logging.
- [Adafruit GPS](https://github.com/adafruit/Adafruit_GPS) — complete-sentence/checksum and valid-fix checks before consuming coordinates.
- [ChirpStack Simulator](https://github.com/brocaar/chirpstack-simulator) — repeatable multi-device uplink simulation and measurable acceptance metrics.

These are references, not copied firmware. Their licenses and hardware assumptions must be reviewed before direct reuse.
