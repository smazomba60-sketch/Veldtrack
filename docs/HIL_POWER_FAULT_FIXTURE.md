# Veldtrack HIL Power and Fault-Injection Fixture

**Status:** Engineering baseline / build specification  
**Revision:** A  
**Target DUT rail:** 5.0 V nominal, 1.0 A continuous, 2.0 A transient maximum  
**Input:** 9–24 VDC current-limited bench supply  
**Control:** External 3.3 V logic or isolated USB-GPIO controller  
**Primary faults:** hard power cut, controlled brownout/load step, input interruption, low-battery sensor emulation

> **Safety boundary:** This is a low-voltage laboratory fixture, not a mains circuit and not a battery charger. Do not connect a Li-ion pack, mains voltage, or an unverified DUT to this design. Confirm the DUT's voltage, current, polarity, and peak-load requirements before energising it.

## 1. Design assumptions and limits

| Parameter | Baseline | Design implication |
|---|---:|---|
| Bench input | 9–24 VDC | Use a current-limited supply; do not exceed 24 V |
| DUT output | 5.0 V nominal | Set buck converter before connecting the DUT |
| Continuous DUT current | 1.0 A | 2 A fuse/current limit is the upper fixture branch limit |
| Transient DUT current | 2.0 A | Verify buck transient response and wiring drop |
| Brownout load | 4.7 Ω / 10 W nominal | Approx. 1.06 A at 5 V; pulse only and monitor resistor temperature |
| Logic control | 3.3 V, active high | `KILL_EN=0` is the safe/off state; do not leave control floating |
| Measurement | VBUS and shunt voltage | Use a differential meter/ADC; never infer current from firmware alone |

If the DUT needs more than 2 A peak, a different high-side switch, shunt, fuse, connector, and thermal design is required. If the DUT is not a 5 V system, change the setpoint, TVS, load, and switch ratings as a coordinated design change—not one component at a time.

## 2. Functional blocks

```text
  J1 9–24 VDC
       |
  F1 resettable fuse + Q1 reverse-polarity MOSFET + D1 TVS
       |
  U1 buck converter, set to 5.10 V, current-limited
       |
  D2 output TVS + C3/C4 bulk decoupling
       |
  Q2 high-side DUT cutoff (KILL_EN; default OFF)
       |
  RSHUNT 50 mΩ / 2 W  ---- TP_IS+ / TP_IS-
       |
  J2 DUT_POWER (protected V_DUT+ and GND)
       |
  Q4 + RLOAD 4.7 Ω / 10 W switched load for brownout injection

  J3 CONTROL: KILL_EN, LOAD_EN/PWM, GND, VMON, ISENSE
  J4 MEASURE: V_IN, V_PRE, V_DUT, GND, ISENSE
```

The deterministic schematic source is [`diagrams/hil-power-fault-fixture.d2`](../diagrams/hil-power-fault-fixture.d2), and the rendered reference image is [`diagrams/hil-power-fault-fixture.png`](../diagrams/hil-power-fault-fixture.png). The BOM is also available as a machine-readable [`HIL_POWER_FAULT_FIXTURE_BOM.csv`](HIL_POWER_FAULT_FIXTURE_BOM.csv).

## 3. Detailed circuit / netlist

### 3.1 Input protection and conversion

| Ref | Connection | Function |
|---|---|---|
| J1-1 | `VIN_RAW+` | 9–24 VDC positive input |
| J1-2 | `GND` | Input return; common with DUT return |
| F1 | `VIN_RAW+` → `VIN_FUSED+` | 2 A resettable fuse / PTC; place next to J1 |
| Q1 | P-channel reverse-polarity stage between `VIN_FUSED+` and `VIN_PROT+` | Body-diode orientation must block reverse input; verify with ohmmeter before power |
| R1 | Q1 gate → `VIN_FUSED+`, 100 kΩ | Keeps Q1 OFF during floating control/startup |
| R2 | Q1 gate → GND, 100 kΩ | Turns Q1 ON for valid positive input; check Q1 VGS rating |
| D1 | `VIN_PROT+` → GND, SMBJ24A unidirectional TVS | Clamps input transients; do not use as a substitute for current limiting |
| C1 | `VIN_PROT+` → GND, 100 µF / 35 V electrolytic | Buck input bulk capacitance |
| C2 | `VIN_PROT+` → GND, 100 nF ceramic | High-frequency input bypass |
| U1 | `VIN_PROT+`, GND → `VBUCK+`, GND | 9–24 V to 5.1 V buck module, >=3 A rated |
| R3/R4 | U1 trim or setpoint network | Set output to 5.10 V unloaded; exact values depend on selected U1 module |

Use a buck module with an accessible current limit or a bench supply with a verified current limit. Do not treat a generic “3 A” module's label as proof of thermal capacity.

### 3.2 DUT rail and hard-cut fault

| Ref | Connection | Function |
|---|---|---|
| D2 | `VBUCK+` → GND, SMBJ5.0A or appropriately selected 5 V TVS | Protects the switched rail from wiring/transient spikes; verify standoff voltage against actual DUT rail |
| C3 | `VBUCK+` → GND, 470 µF / 10 V low-ESR | Local bulk storage before cutoff/load step |
| C4 | `VBUCK+` → GND, 100 nF ceramic | High-frequency bypass |
| Q2 | P-channel high-side MOSFET, source=`VBUCK+`, drain=`VSW+` | Disconnects DUT rail for hard power-cut tests |
| R5 | Q2 gate → source, 100 kΩ | Default OFF / fails safe if control is unplugged |
| Q3 | N-channel gate pull-down, drain=Q2 gate, source=GND | Drives Q2 ON when `KILL_EN` is asserted |
| R6 | `KILL_EN` → Q3 gate, 10 kΩ | Limits control input current |
| R7 | Q3 gate → GND, 100 kΩ | Prevents floating gate turn-on |
| D3 | Q2 gate-source clamp, 10 V zener | Protects Q2 VGS during input transients; cathode to source |
| RSHUNT | `VSW+` → `V_DUT+`, 50 mΩ / 2 W, 1% | Current measurement; Kelvin sense pads recommended |
| C5 | `V_DUT+` → GND, 100 µF / 10 V | DUT-side local capacitance; document this capacitance in test reports |
| C6 | `V_DUT+` → GND, 100 nF ceramic | DUT-side high-frequency bypass |
| J2-1 | `V_DUT+` | Protected DUT positive output |
| J2-2 | `GND` | DUT return |

**Control polarity:** `KILL_EN=0` means Q2 OFF and the DUT is unpowered. `KILL_EN=3.3 V` means Q2 ON and the DUT is powered. The host harness must assert `KILL_EN` only after preflight and must deassert it on timeout, host failure, or emergency stop.

### 3.3 Controlled brownout / load-step fault

| Ref | Connection | Function |
|---|---|---|
| Q4 | N-channel power MOSFET, drain=`V_DUT_LOAD+`, source=GND | Low-side switch for injected load |
| RLOAD | `V_DUT+` → Q4 drain, 4.7 Ω / 10 W wirewound | Draws about 1.06 A at 5 V; creates a controlled voltage sag when the source/current limit is reached |
| R8 | `LOAD_EN/PWM` → Q4 gate, 100 Ω | Gate ringing/current limiting |
| R9 | Q4 gate → GND, 100 kΩ | Load defaults OFF |
| D4 | Optional flyback diode only if an inductive load is substituted | Not required for RLOAD; never install a diode across a purely resistive load as a “fix” |
| TP_LOAD | Q4 drain | Scope point for load-switch waveform |

For a brownout, configure the supply/current limiter and assert `LOAD_EN` for a controlled pulse. Start with 10 ms, then increase only while monitoring `V_DUT+`, Q4 temperature, RLOAD temperature, and DUT reset behavior. This fixture does **not** create a precision brownout voltage; it creates a documented load step whose resulting sag must be measured.

### 3.4 Measurement and control headers

| Connector | Pin | Net | Requirement |
|---|---:|---|---|
| J3 CONTROL | 1 | `KILL_EN` | 3.3 V logic output, default low |
| J3 CONTROL | 2 | `LOAD_EN/PWM` | 3.3 V logic output, default low |
| J3 CONTROL | 3 | `GND` | Common logic return |
| J3 CONTROL | 4 | `VMON` | High-impedance monitor of `V_DUT+`; divider required before MCU ADC |
| J3 CONTROL | 5 | `ISENSE` | Differential sense of RSHUNT; do not connect directly to a single-ended ADC without scaling |
| J4 MEASURE | 1 | `VIN_RAW+` | Input voltage test point |
| J4 MEASURE | 2 | `VIN_PROT+` | Post-protection / buck input test point |
| J4 MEASURE | 3 | `VBUCK+` | Pre-cutoff 5.1 V rail |
| J4 MEASURE | 4 | `V_DUT+` | DUT voltage at connector side of shunt |
| J4 MEASURE | 5 | `TP_IS+` | Shunt high side |
| J4 MEASURE | 6 | `TP_IS-` | Shunt low side |
| J4 MEASURE | 7 | `GND` | Measurement return |

**Current equation:** `I_DUT = (V(TP_IS+) - V(TP_IS-)) / 0.050 Ω`. At 1 A, the shunt drop is 50 mV and dissipation is 50 mW; the 2 W rating provides margin for transients and wiring temperature.

## 4. BOM

Values marked **TBD by board selection** must be finalised against the DUT schematic and the chosen module datasheet before PCB release.

| Item | Qty | Suggested part / minimum specification | Key ratings / notes | Required |
|---|---:|---|---|---|
| J1 | 1 | 2-pin locking screw terminal, 5.08 mm pitch | >=30 VDC, >=5 A; keyed polarity marking | Yes |
| F1 | 1 | Polyfuse MF-R200 or equivalent | 2.0 A hold/trip family; confirm trip behavior at ambient | Yes |
| Q1 | 1 | P-MOSFET, e.g. DMP3010UFZ or equivalent | >=30 V, low RDS(on) at available gate drive, current >=5 A | Yes |
| D1 | 1 | SMBJ24A | 24 V standoff; verify input maximum is <=24 V | Yes |
| R1/R2 | 2 | 100 kΩ, 1% resistor | Q1 gate bias | Yes |
| C1 | 1 | 100 µF, 35 V electrolytic | Low ESR, radial | Yes |
| C2 | 1 | 100 nF, 50 V X7R | Input bypass | Yes |
| U1 | 1 | Adjustable buck module, e.g. MP1584/LM2596 class | Input >=28 V, output 5 V, >=3 A advertised; current-limit verification required | Yes |
| R3/R4 | 1 set | U1-specific feedback/trim parts | **TBD by U1**; do not populate generic values blindly | Yes |
| D2 | 1 | 5 V TVS selected for actual rail | Standoff above maximum normal rail and below DUT damage limit | Yes |
| C3 | 1 | 470 µF, 10 V low-ESR electrolytic | Pre-cutoff bulk | Yes |
| C4/C6 | 2 | 100 nF, 10 V X7R | Rail bypass | Yes |
| Q2 | 1 | P-MOSFET, e.g. IRLML6402 or equivalent | >=20 V, low RDS(on) at -4.5 V, >=3 A pulsed; check thermal path | Yes |
| Q3 | 1 | 2N7002 or BSS138 | Gate pull-down driver; 3.3 V compatible | Yes |
| R5/R7/R9 | 3 | 100 kΩ, 1% resistor | Safe-default pull-ups/pull-downs | Yes |
| R6 | 1 | 10 kΩ, 1% resistor | Q3 gate series / control protection | Yes |
| D3 | 1 | 10 V zener, BZT52C10 or equivalent | Q2 gate-source clamp | Yes |
| RSHUNT | 1 | 0.050 Ω, 2 W, 1% four-terminal preferred | Kelvin pads; current measurement | Yes |
| C5 | 1 | 100 µF, 10 V low-ESR electrolytic | DUT-side bulk; replace only with documented DUT fixture value | Yes |
| J2 | 1 | 2-pin locking DUT connector | >=5 VDC, >=5 A; keyed and strain relieved | Yes |
| Q4 | 1 | Logic-level N-MOSFET, e.g. IRLZ44N for through-hole or equivalent | >=30 V, >=10 A, low RDS(on) at 4.5 V; heatsink provision | Yes |
| RLOAD | 1 | 4.7 Ω, 10 W wirewound resistor | Pulse-rated; starts at 10 ms load pulses; mount away from plastics | Yes |
| R8 | 1 | 100 Ω, 1% resistor | Q4 gate resistor | Yes |
| D4 | 1 | 1N5819 or equivalent | Populate only for an inductive load option | Optional |
| J3 | 1 | 5-pin 2.54 mm control header | KILL_EN, LOAD_EN/PWM, GND, VMON, ISENSE | Yes |
| J4 | 1 | 7-pin 2.54 mm measurement header | Exposed voltage/current points | Yes |
| TP1–TP7 | 7 | Shrouded test points | Labeled; prevent accidental shorting | Yes |
| SW1 | 1 | Latching emergency-stop / kill switch | Series with `KILL_EN` or control power; default safe state | Recommended |
| LED1 | 1 | Green LED + 1 kΩ resistor | `V_DUT+` present indication | Recommended |
| LED2 | 1 | Amber LED + 1 kΩ resistor | `LOAD_EN` indication | Recommended |
| PCB/fixture | 1 | FR-4 PCB or insulated DIN-rail enclosure | Creepage/clearance appropriate to low voltage; guarded terminals | Yes |
| F2 | 1 | 2 A inline fuse or resettable fuse on DUT branch | Secondary protection if wiring leaves enclosure | Recommended |
| Host controller | 1 | Isolated USB-GPIO or small 3.3 V MCU | Must default both outputs low on boot/disconnect | Recommended |
| Meter | 1 | Calibrated DMM / USB power meter | Voltage/current verification | Yes |
| Scope | 1 | 2+ channel oscilloscope, differential probe preferred | Brownout and reset timing evidence | Recommended |

**Component-selection note:** The suggested MOSFETs and buck module are starting points, not a substitute for checking the exact datasheet, package thermal resistance, gate drive, PCB copper, pulse duration, and DUT inrush current. Record the final manufacturer part numbers in the build manifest.

## 5. Wiring and bring-up procedure

1. Assemble the fixture with no DUT connected. Inspect polarity, MOSFET orientation, TVS polarity, fuse placement, shunt pads, and connector labels.
2. With a DMM in resistance/diode mode, verify no short from `VIN_PROT+`, `VBUCK+`, or `V_DUT+` to GND. Verify Q2 is OFF when `KILL_EN` is disconnected.
3. Set the bench supply to 12 V, current limit 0.25 A, and connect through J1. Confirm the input current is low and no component heats.
4. Measure U1 output and adjust to **5.10 V ±0.05 V** with Q2 OFF. Increase current limit only after this test passes.
5. Assert `KILL_EN`; verify `V_DUT+` rises to within 100 mV of `VBUCK+` with no DUT connected. Deassert it and verify `V_DUT+` falls below 0.5 V within the measured cutoff time.
6. Connect a known 100 Ω / 1 W dummy load to J2. Confirm polarity and approximately 50 mA load current.
7. Verify shunt polarity and calculate current from `ISENSE`; compare against the DMM to within ±5%.
8. Pulse `LOAD_EN` for 10 ms with the dummy load present. Confirm Q4 and RLOAD stay within safe temperature limits; do not begin DUT brownout tests until the waveform is captured.
9. Connect the DUT with its current limit set conservatively. Record boot current, steady current, inrush, and rail voltage before running HIL cases.

## 6. Fault-injection recipes

### Hard power cut

- DUT running and logging.
- Capture `V_DUT+`, DUT reset/log line, and radio/GNSS rails if accessible.
- Deassert `KILL_EN` for at least 1 s.
- Reassert `KILL_EN` and verify `BOOT` contains the expected reset reason.
- Pass only if no partial telemetry frame is accepted and the post-boot sequence policy matches the firmware requirement.

### Brownout / load step

- Start with `LOAD_EN/PWM` pulse = 10 ms.
- Monitor `V_DUT+`, DUT current, Q4 drain, and reset line.
- Increase pulse width or reduce source current limit one variable at a time.
- Record the minimum measured `V_DUT+`, pulse duration, whether reset occurred, and whether the DUT recovered.
- Do not call this a controlled voltage test unless a programmable supply or electronic load closes the voltage-control loop.

### Input interruption

- Use the bench supply's output-enable or a rated series relay; do not manually short the input.
- Verify F1 and TVS remain intact after the test.
- Never interrupt a live inductive supply without checking for overshoot on `VIN_PROT+`.

## 7. Acceptance checklist

- [ ] Final DUT voltage/current limits approved and recorded.
- [ ] Final MOSFET, TVS, buck, fuse, connector, and shunt part numbers recorded.
- [ ] Q1/Q2/Q3/Q4 orientation verified against the assembled board.
- [ ] Both control outputs default LOW on controller boot and cable disconnect.
- [ ] Emergency stop removes or inhibits `KILL_EN`.
- [ ] Input and DUT branch protection tested.
- [ ] U1 output set to 5.10 V ±0.05 V without DUT.
- [ ] Hard cutoff measured and captured.
- [ ] Brownout load waveform and thermal check captured.
- [ ] Voltage/current measurement agrees with calibrated instruments within ±5%.
- [ ] HIL run artifacts follow `docs/HIL_TEST_HARNESS.md`.
- [ ] No mains, battery charging, or production-network assumptions have been introduced.
