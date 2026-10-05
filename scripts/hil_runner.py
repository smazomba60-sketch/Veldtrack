#!/usr/bin/env python3
"""Veldtrack HIL brownout/fault-injection runner.

The default ``sim`` mode is deterministic and CI-safe. ``external`` mode
calls a user-supplied rig helper, one JSON request per invocation, so the
runner does not guess the protocol of a particular power controller, DUT
serial adapter, or radio backend.

External helper contract:
  helper receives one JSON object on stdin and prints one JSON object on stdout.
  Supported actions: preflight, power_on, power_off, brownout, hard_cut,
  configure, collect.
  ``collect`` returns {"events": [...], "uplinks": [...]}.
  Any non-zero exit, malformed JSON, timeout, or ``ok:false`` is a hard FAIL.

Example:
  python scripts/hil_runner.py --mode sim --cycles 1000
  python scripts/hil_runner.py --mode external --rig-command \
      ./hardware/veldtrack_rig_helper --cycles 1000 --artifacts artifacts/hil
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def make_run_id() -> str:
    return f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"


class Rig(Protocol):
    def preflight(self, run_id: str) -> dict[str, Any]: ...
    def power_on(self) -> dict[str, Any]: ...
    def power_off(self) -> dict[str, Any]: ...
    def brownout(self, duration_ms: int) -> dict[str, Any]: ...
    def hard_cut(self, duration_ms: int) -> dict[str, Any]: ...
    def configure(self, scenario: str, cycle: int) -> dict[str, Any]: ...
    def collect(self, timeout_s: float) -> dict[str, Any]: ...


@dataclass
class SimulatedRig:
    """Deterministic stand-in for a real DUT/power/radio rig."""

    device_id: str = "sim-cow-001"
    sequence: int = 0
    powered: bool = False
    events: list[dict[str, Any]] = field(default_factory=list)
    uplinks: list[dict[str, Any]] = field(default_factory=list)
    scenario: str = "nominal"
    cycle: int = 0
    _event_cursor: int = 0
    _uplink_cursor: int = 0

    def _event(self, event: str, **fields: Any) -> None:
        self.events.append({"event": event, "monotonic_ms": len(self.events) * 10, **fields})

    def preflight(self, run_id: str) -> dict[str, Any]:
        return {"ok": True, "backend": "simulated", "run_id": run_id}

    def power_on(self) -> dict[str, Any]:
        self.powered = True
        self._event("BOOT", firmware_version="sim-1", board_id="SIM", device_id=self.device_id, reset_reason="power_on")
        return {"ok": True}

    def power_off(self) -> dict[str, Any]:
        self.powered = False
        return {"ok": True}

    def brownout(self, duration_ms: int) -> dict[str, Any]:
        if not self.powered:
            return {"ok": False, "error": "brownout while powered off"}
        self._event("WATCHDOG_RESET", reset_reason="brownout", duration_ms=duration_ms)
        return {"ok": True, "duration_ms": duration_ms}

    def hard_cut(self, duration_ms: int) -> dict[str, Any]:
        self.powered = False
        return {"ok": True, "duration_ms": duration_ms}

    def configure(self, scenario: str, cycle: int) -> dict[str, Any]:
        self.scenario, self.cycle = scenario, cycle
        return {"ok": True, "scenario": scenario, "cycle": cycle}

    def collect(self, timeout_s: float) -> dict[str, Any]:
        if not self.powered:
            return {"ok": False, "error": "collect while powered off"}
        self._event("GNSS_STATUS", fix=True, latitude=-29.6100 + self.cycle / 1_000_000, longitude=30.3900, fix_age_ms=0, satellites=10, hdop=1.2)
        if self.scenario == "persistent_radio_failure":
            self._event("TX_FAIL", sequence=self.sequence, attempts=4, error_class="no_network")
            events = self.events[self._event_cursor:]
            uplinks = self.uplinks[self._uplink_cursor:]
            self._event_cursor, self._uplink_cursor = len(self.events), len(self.uplinks)
            return {"ok": True, "events": events, "uplinks": uplinks}
        attempts = 3 if self.scenario == "transient_radio_loss" else 1
        self._event("TX_ATTEMPT", sequence=self.sequence, reason="periodic", payload_hash=f"sim-{self.sequence}", attempt=1)
        for attempt in range(2, attempts + 1):
            self._event("TX_ATTEMPT", sequence=self.sequence, reason="periodic", payload_hash=f"sim-{self.sequence}", attempt=attempt)
        payload = {
            "device_id": self.device_id,
            "sequence": self.sequence,
            "timestamp": now_utc(),
            "latitude": -29.6100 + self.cycle / 1_000_000,
            "longitude": 30.3900,
            "battery_pct": 80.0,
            "motion": True,
            "gps_fix": True,
            "reason": "periodic",
        }
        self.uplinks.append(payload)
        self._event("TX_ACK", sequence=self.sequence, payload_hash=f"sim-{self.sequence}", attempts=attempts, network_metadata={"backend": "sim"})
        self.sequence += 1
        events = self.events[self._event_cursor:]
        uplinks = self.uplinks[self._uplink_cursor:]
        self._event_cursor, self._uplink_cursor = len(self.events), len(self.uplinks)
        return {"ok": True, "events": events, "uplinks": uplinks}


@dataclass
class ExternalCommandRig:
    command: list[str]
    timeout_s: float = 30.0

    def _call(self, action: str, **fields: Any) -> dict[str, Any]:
        request = {"action": action, **fields}
        try:
            proc = subprocess.run(
                self.command,
                input=json.dumps(request) + "\n",
                text=True,
                capture_output=True,
                timeout=self.timeout_s,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"rig helper {action} failed: {exc}") from exc
        if proc.returncode != 0:
            raise RuntimeError(f"rig helper {action} exited {proc.returncode}: {proc.stderr[-500:]}")
        try:
            result = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"rig helper {action} returned invalid JSON") from exc
        if not result.get("ok", False):
            raise RuntimeError(f"rig helper {action} rejected request: {result.get('error', 'unknown error')}")
        return result

    def preflight(self, run_id: str) -> dict[str, Any]: return self._call("preflight", run_id=run_id)
    def power_on(self) -> dict[str, Any]: return self._call("power_on")
    def power_off(self) -> dict[str, Any]: return self._call("power_off")
    def brownout(self, duration_ms: int) -> dict[str, Any]: return self._call("brownout", duration_ms=duration_ms)
    def hard_cut(self, duration_ms: int) -> dict[str, Any]: return self._call("hard_cut", duration_ms=duration_ms)
    def configure(self, scenario: str, cycle: int) -> dict[str, Any]: return self._call("configure", scenario=scenario, cycle=cycle)
    def collect(self, timeout_s: float) -> dict[str, Any]: return self._call("collect", timeout_s=timeout_s)


@dataclass
class CycleResult:
    cycle: int
    scenario: str
    ok: bool
    reason: str = ""
    events: list[dict[str, Any]] = field(default_factory=list)
    uplinks: list[dict[str, Any]] = field(default_factory=list)


def validate_cycle(cycle: int, scenario: str, result: dict[str, Any], expected_sequence: int) -> CycleResult:
    events = result.get("events", [])
    uplinks = result.get("uplinks", [])
    names = {e.get("event") for e in events}
    required = {"BOOT", "GNSS_STATUS"}
    if scenario == "brownout":
        required.add("WATCHDOG_RESET")
    elif scenario == "persistent_radio_failure":
        required.add("TX_FAIL")
    else:
        required.add("TX_ACK")
    missing = required - names
    if missing:
        return CycleResult(cycle, scenario, False, f"missing events: {sorted(missing)}", events, uplinks)
    accepted = [u for u in uplinks if u.get("gps_fix") is True]
    if scenario == "persistent_radio_failure":
        if any(e.get("event") == "TX_ACK" for e in events) or accepted:
            return CycleResult(cycle, scenario, False, "persistent radio failure produced an uplink", events, uplinks)
    elif len(accepted) != 1:
        return CycleResult(cycle, scenario, False, f"expected one accepted uplink, got {len(accepted)}", events, uplinks)
    else:
        payload = accepted[0]
        if payload.get("sequence") != expected_sequence:
            return CycleResult(cycle, scenario, False, "sequence mismatch", events, uplinks)
        if not (-90 <= payload.get("latitude", 999) <= 90 and -180 <= payload.get("longitude", 999) <= 180):
            return CycleResult(cycle, scenario, False, "coordinate out of range", events, uplinks)
    return CycleResult(cycle, scenario, True, events=events, uplinks=uplinks)


def run_sequence(rig: Rig, cycles: int, artifacts: Path, run_id: str, timeout_s: float = 10.0) -> dict[str, Any]:
    if cycles < 1:
        raise ValueError("cycles must be >= 1")
    artifacts.mkdir(parents=True, exist_ok=True)
    manifest = {
        "run_id": run_id,
        "started_at_utc": now_utc(),
        "cycles_requested": cycles,
        "runner": "scripts/hil_runner.py",
        "mode": "simulated" if isinstance(rig, SimulatedRig) else "external",
    }
    (artifacts / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    all_events: list[dict[str, Any]] = []
    all_uplinks: list[dict[str, Any]] = []
    results: list[CycleResult] = []
    fatal: str | None = None
    expected_sequence = 0
    try:
        rig.preflight(run_id)
        for cycle in range(cycles):
            # The rotation exercises every fault path while keeping the run bounded.
            scenario = ["brownout", "hard_cut", "transient_radio_loss", "persistent_radio_failure"][cycle % 4]
            rig.configure(scenario, cycle)
            rig.power_on()
            if scenario == "brownout":
                rig.brownout(duration_ms=10 + cycle % 3)
            elif scenario == "hard_cut":
                rig.hard_cut(duration_ms=1_000)
                rig.power_on()
            result = rig.collect(timeout_s)
            cycle_result = validate_cycle(cycle, scenario, result, expected_sequence=expected_sequence)
            results.append(cycle_result)
            all_events.extend({"cycle": cycle, **e} for e in cycle_result.events)
            all_uplinks.extend({"cycle": cycle, **u} for u in cycle_result.uplinks)
            if not cycle_result.ok:
                fatal = cycle_result.reason
                break
            if scenario != "persistent_radio_failure":
                expected_sequence += 1
    except Exception as exc:  # fail closed and preserve the error in the verdict
        fatal = str(exc)
    finally:
        try:
            rig.power_off()
        except Exception as exc:
            fatal = fatal or f"safe power-off failed: {exc}"

    (artifacts / "dut-events.ndjson").write_text("".join(json.dumps(x, sort_keys=True) + "\n" for x in all_events))
    (artifacts / "radio-uplinks.ndjson").write_text("".join(json.dumps(x, sort_keys=True) + "\n" for x in all_uplinks))
    verdict = {
        "run_id": run_id,
        "finished_at_utc": now_utc(),
        "cycles_requested": cycles,
        "cycles_completed": len(results),
        "passed": sum(r.ok for r in results),
        "failed": sum(not r.ok for r in results),
        "ok": fatal is None and len(results) == cycles and all(r.ok for r in results),
        "fatal_error": fatal,
        "failures": [{"cycle": r.cycle, "scenario": r.scenario, "reason": r.reason} for r in results if not r.ok],
    }
    (artifacts / "verdict.json").write_text(json.dumps(verdict, indent=2, sort_keys=True) + "\n")
    return verdict


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Veldtrack 1,000-cycle HIL brownout/fault sequence")
    parser.add_argument("--mode", choices=("sim", "external"), default="sim")
    parser.add_argument("--cycles", type=int, default=1000)
    parser.add_argument("--artifacts", type=Path, default=Path("artifacts/hil/latest"))
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--timeout", type=float, default=10.0, help="seconds to wait for DUT/radio collection")
    parser.add_argument("--rig-command", nargs=argparse.REMAINDER, help="external helper command after --rig-command")
    args = parser.parse_args(argv)
    if args.mode == "external" and not args.rig_command:
        parser.error("--mode external requires --rig-command COMMAND")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    run_id = args.run_id or make_run_id()
    rig: Rig
    if args.mode == "sim":
        rig = SimulatedRig()
    else:
        rig = ExternalCommandRig(args.rig_command)
    verdict = run_sequence(rig, args.cycles, args.artifacts / run_id, run_id, args.timeout)
    print(json.dumps(verdict, indent=2, sort_keys=True))
    return 0 if verdict["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
