# Veldtrack Hardware-in-the-Loop Test Harness Specification

**Status:** Proposed implementation specification  
**Scope:** Real GNSS receiver, real radio module, target board, power path, and host-controlled acceptance tests  
**Owner:** Veldtrack firmware/hardware team  
**Version:** 1.0

## 1. Purpose and limits

This harness verifies that the assembled Veldtrack device can acquire a real position, apply the firmware safety gates, transmit telemetry through the selected radio path, recover from faults, and produce auditable evidence.

It is an **acceptance gate**, not a guarantee of performance in every pasture. Field confidence still requires environmental, enclosure, battery-life, range, and multi-day livestock trials.

The harness must support two complementary modes:

| Mode | What it proves | Determinism |
|---|---|---|
| **Real-sky GNSS + real radio** | Electrical integration, antenna, acquisition, firmware timing, radio/network path | Medium; log RF/weather conditions |
| **NMEA replay + real radio** | Parser, fix validity, stale-fix behavior, payload and retry logic | High; use checked-in fixtures |

A GNSS RF simulator may replace real-sky acquisition for repeatable cold-start and bad-signal tests, but it is optional and must be recorded in the test report.

## 2. System under test

The Device Under Test (DUT) is the complete assembled board and firmware, including:

- MCU and bootloader
- GNSS module, antenna, power rail, and UART/I2C/SPI connection
- Radio module, antenna, SIM/eSIM or LoRaWAN credentials, and power rail
- Motion sensor and battery-voltage measurement path
- Firmware adapter that calls the existing `VeldtrackDevice` core seams:
  - `feed_gps(now, latitude, longitude, fix)`
  - `feed_sensors(battery_pct, motion)`
  - `tick(now)`
  - `Transport.send(payload)`

The host harness is not allowed to replace the DUT's parser, retry logic, clock handling, or radio driver in a real-radio test. It may provide fixtures, observe logs, inject controlled power/faults, and verify received uplinks.

## 3. Required harness components

### 3.1 Host controller

A Linux host or CI runner with:

- Two independently addressable serial interfaces:
  - **DUT control/log port**: firmware console and test commands.
  - **GNSS monitor/injection port**: only for replay-capable fixtures; never electrically parallel a powered real GNSS TX line without an approved multiplexer.
- Python 3.11+ and the repository checkout.
- UTC-synchronised clock; record `chronyc tracking` or equivalent in the test artifact.
- A unique run ID and immutable raw logs.
- Optional USB power meter and programmable power supply control.

### 3.2 GNSS fixture

One of:

1. **Real-sky antenna fixture:** GNSS antenna with unobstructed sky view, strain relief, and a known reference coordinate surveyed to at least 10 m.
2. **GNSS RF simulator:** configured scenario with known coordinates, time, satellite visibility, and controlled signal loss.
3. **NMEA replay fixture:** a serial-level fixture or firmware test mode that replays complete, checksum-valid and invalid NMEA sentences from `tests/fixtures/gnss/`.

The harness must record GNSS fix type, satellite count, HDOP/accuracy if available, first-fix time, and the source mode.

### 3.3 Radio fixture

The selected radio determines the backend:

- **LoRaWAN:** real gateway, network-server/application integration, device credentials, and an isolated test application. Prefer conducted RF with attenuators for repeatable range-independent tests; use an antenna only in an approved lab band plan.
- **LTE-M/NB-IoT:** real modem, approved test SIM/eSIM, carrier APN, and a receiver endpoint or MQTT/HTTPS test broker. Record registration state, RAT, RSSI/RSRP, RSRQ, and operator.
- **Other packet radio:** a receiver/bridge that can verify device ID, sequence, payload bytes, timestamp, and acknowledgement semantics.

The receiver must expose a machine-readable uplink feed to the host harness. A screenshot-only dashboard is not an acceptable oracle.

### 3.4 Power and fault fixtures

Required for release qualification:

- Current-limited bench supply with voltage and current logging.
- Programmable power interruption or a documented manual reset procedure.
- Optional electronic load and battery emulator.
- Logic analyser access to GNSS and radio buses for diagnosing failures.

Never connect a bench supply and battery in parallel unless the board explicitly supports it. Use current limits and a fuse appropriate to the DUT.

## 4. DUT observability contract

The firmware must emit newline-delimited JSON on the control/log port. Every record contains:

```json
{"run_id":"2026-10-05T20:00:00Z-abc123","event":"TX_ACK","monotonic_ms":12345,"sequence":7}
```

Required events:

| Event | Required fields | Meaning |
|---|---|---|
| `BOOT` | firmware version, board ID, device ID, reset reason | First event after reset |
| `GNSS_STATUS` | fix, latitude, longitude, fix age ms, satellites, hdop | Latest GNSS state; omit coordinates when invalid |
| `SENSOR_STATUS` | battery percent/voltage, motion | Latest sensor state |
| `TX_ATTEMPT` | sequence, reason, payload hash, attempt | Radio send started |
| `TX_ACK` | sequence, payload hash, attempts, network metadata | Uplink accepted/acknowledged |
| `TX_FAIL` | sequence, attempts, error class | Retry budget exhausted |
| `WATCHDOG_RESET` | reset reason, uptime ms | Main loop recovery |
| `ERROR` | stable error class and message | Unrecoverable or diagnostic fault |
| `TEST_END` | verdict, counts | Device-side test completion marker |

Rules:

- Logs must not contain credentials, SIM secrets, join keys, or access tokens.
- `payload_hash` is SHA-256 of the exact bytes handed to the radio driver, not a hash of a pretty-printed object.
- Host timestamps and DUT monotonic timestamps must both be retained; do not infer timing from log order alone.
- The DUT must provide a test command to set a known device clock or report whether time comes from GNSS/network. Production clock-setting commands must be disabled or authenticated outside the harness.

## 5. Host harness interface

The initial harness may be a Python script or test runner, but it must implement these adapters:

```python
class DutAdapter(Protocol):
    def reset(self) -> None: ...
    def command(self, name: str, **kwargs) -> None: ...
    def events(self, timeout_s: float) -> list[dict]: ...

class GnssAdapter(Protocol):
    def start(self, scenario: str) -> None: ...
    def stop(self) -> None: ...

class RadioOracle(Protocol):
    def clear(self, run_id: str) -> None: ...
    def wait_for_uplink(self, device_id: str, sequence: int, timeout_s: float) -> dict: ...

class PowerAdapter(Protocol):
    def set_voltage(self, volts: float) -> None: ...
    def cycle(self, off_ms: int) -> None: ...
```

The existing simulator loop remains the fast pre-HIL gate. The HIL runner adds the real adapters and must fail closed when a required adapter is unavailable.

Recommended command shape on the DUT control port:

```text
TEST START run_id=<id> mode=<real_sky|nmea_replay|rf_sim>
TEST GNSS scenario=<valid|no_fix|stale|invalid_checksum>
TEST RADIO scenario=<normal|drop_first_n|no_network>
TEST STOP
```

The exact transport (JSON lines, CBOR, or another framing) may change with the MCU, but event names and required semantics must remain stable.

## 6. Test scenarios and acceptance criteria

Every case produces: `run.json`, raw DUT log, GNSS source/log, radio-oracle log, power log if used, firmware/build identifiers, wiring/photo reference, and a PASS/FAIL summary.

| ID | Scenario | Procedure | Pass criteria |
|---|---|---|---|
| HIL-GNSS-001 | Cold start, real sky | Power DUT off for >=60 s; expose antenna; start timer at power-on | `BOOT` occurs; valid fix reported; first valid fix is within the project target or the target is recorded as TBD; coordinates are within 30 m of reference or receiver's documented accuracy, whichever is stricter |
| HIL-GNSS-002 | No fix safety gate | Shield/disconnect antenna or run no-fix scenario; wait one report interval | Zero radio uplinks containing coordinates; `GNSS_STATUS.fix=false`; no `TX_ACK` for a location report |
| HIL-GNSS-003 | Invalid NMEA/checksum | Replay malformed and bad-checksum sentences, then a valid sentence | Invalid frames are ignored; no crash; no position update until a valid fix; valid sentence later produces exactly one accepted telemetry report |
| HIL-GNSS-004 | Stale fix | Establish a fix, stop GNSS updates for > `gps_stale_after`, keep main loop alive | Zero stale-coordinate uplinks; diagnostic state is `blocked_stale_fix` or equivalent; recovery after a fresh fix is accepted |
| HIL-RADIO-001 | Nominal uplink | Real fix, normal gateway/network, one report interval | Receiver gets one payload with matching device ID, sequence, coordinates, timestamp, battery, motion, and reason; end-to-end latency is recorded |
| HIL-RADIO-002 | Transient loss and retry | Drop the first two sends, restore receiver before retry budget expires | One eventual accepted payload; no sequence skip or duplicate accepted sequence; `TX_ATTEMPT` count equals observed attempts |
| HIL-RADIO-003 | Persistent radio failure | Make receiver unavailable for longer than retry budget | `TX_FAIL` after exactly the configured bounded attempts; firmware remains responsive; next scheduled report can retry without corrupting sequence state |
| HIL-RADIO-004 | Radio recovery | Fail radio, restore it, then provide a fresh fix | A later fresh payload is accepted; no stale queued position is sent unless explicitly required by product policy |
| HIL-POWER-001 | Brownout/reboot | Reduce supply through the board's specified operating range or interrupt power | Reset reason is logged; no malformed partial payload; after boot and fresh fix, device resumes with a defined sequence policy |
| HIL-POWER-002 | Low battery alert | Use battery emulator or controlled sensor input below `low_battery_pct` | Immediate low-battery report is accepted; payload reason is `low_battery`; alert cadence is bounded to product policy |
| HIL-SYS-001 | Watchdog recovery | Stall/suspend the main loop beyond watchdog threshold | Exactly one watchdog reset event per induced stall; device boots and can acquire a fresh fix and transmit |
| HIL-SYS-002 | 24-hour soak | Run real board, real GNSS, and real radio for 24 h at configured cadence | No unexplained reboot, memory growth, duplicate sequence, invalid coordinate, stale-coordinate uplink, or unbounded error log; packet delivery ratio meets the product target |

### Provisional release thresholds

Until the product requirements specify otherwise, use these gates and label them **provisional**:

- 100% pass for all safety-gate cases (`HIL-GNSS-002` through `HIL-GNSS-004`).
- 100% schema and sequence correctness for all accepted uplinks.
- At least 3 successful nominal runs on each supported board/radio/GNSS combination.
- At least 10 transient-loss runs with no sequence corruption.
- Zero unexplained resets during the 24-hour soak.
- Packet delivery, first-fix time, latency, current draw, and battery life must be recorded; final numeric product limits require product-owner approval.

## 7. Test execution sequence

1. **Preflight:** verify board revision, firmware hash, fixture calibration, antenna connections, credentials loaded through the secret store, and safe RF configuration.
2. **Static smoke:** run unit tests and `python scripts/loop_test.py 1000`.
3. **Power-on:** start run ID, power meter, host capture, and DUT log capture before energising the DUT.
4. **GNSS:** execute no-fix, invalid-input/replay, then real-sky acquisition. Do not mark a no-fix test passed merely because the radio is offline.
5. **Radio:** execute nominal, transient-loss, persistent-failure, and recovery cases with the real receiver oracle.
6. **Recovery:** execute brownout and watchdog cases only with a current-limited supply and a reset-safe fixture.
7. **Soak:** run the 24-hour profile, rotate logs safely, and preserve the raw evidence.
8. **Verdict:** generate a machine-readable summary. Any missing required artifact, timeout, unexpected event, safety-gate violation, or oracle mismatch is FAIL—not INCONCLUSIVE.
9. **Review:** attach the report to the firmware/build record and record board, module, antenna, network, location, weather, and operator.

## 8. Evidence and report schema

Each run directory should contain:

```text
artifacts/hil/<run_id>/
  manifest.json
  verdict.json
  dut-events.ndjson
  gnss-source.ndjson
  radio-uplinks.ndjson
  power.csv
  host.log
  wiring-orientation.txt
```

Minimum `manifest.json` fields:

```json
{
  "run_id": "...",
  "firmware_commit": "...",
  "board_revision": "...",
  "gnss_module": "...",
  "radio_module": "...",
  "radio_backend": "lorawan|lte_m|other",
  "gnss_mode": "real_sky|nmea_replay|rf_sim",
  "host": "...",
  "started_at_utc": "...",
  "operator": "..."
}
```

The verdict must include per-case status, observed metrics, failure reason, and a link or checksum for every raw artifact. Never overwrite a failed run with a later pass.

## 9. Security and lab safety

- Use a dedicated test application, test tenant, or broker namespace; do not publish HIL traffic into production livestock data.
- Keep LoRaWAN frequencies, transmit power, LTE credentials, and radio exposure within local regulations and the module's approved limits.
- Store credentials in environment variables or a secret manager; never commit them to fixtures or logs.
- Use RF attenuation or an approved screened setup for conducted radio tests. Do not connect a transmitter to a spectrum analyser without the specified attenuator.
- Apply current limiting, fusing, polarity protection, and thermal monitoring before unattended runs.
- Obtain explicit approval before any test that intentionally transmits over public networks or leaves the lab.

## 10. Exit criteria for a real hardware release

A board/firmware combination is HIL-qualified only when:

- All mandatory cases pass on the exact production candidate build.
- The evidence bundle is complete and reproducible.
- No safety-gate or data-integrity defect is waived without a dated, signed decision.
- Power, first-fix, latency, radio delivery, and reset behavior are compared with the product requirements.
- At least one subsequent field trial is planned; HIL qualification alone does not replace field validation.
