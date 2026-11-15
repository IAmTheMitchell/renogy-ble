# Renogy BLE Library Developer Specification

## Scope

`renogy-ble` is a standalone Python library for communicating with supported
Renogy Bluetooth Low Energy devices. It owns BLE transport, Modbus request
construction and validation, device-specific read flows, and response parsing.

The library must remain independent of Home Assistant. Home Assistant lifecycle,
entity, and configuration behavior belongs in `renogy-ha`.

## Supported Device Types

The public `device_type` values and their transport paths are:

| Device type | Transport and protocol |
| --- | --- |
| `controller` | Controller-style Modbus reads, normally through BT-1 or BT-2 |
| `dcc` | DC-DC charger register map using the controller-style Modbus transport |
| `battery` | Legacy, Battery Pro, or RNGPRO battery commands and parsing |
| `inverter` | Inverter-specific Modbus registers and BLE session handling |
| `shunt300` | Smart Shunt 300 notification parsing |

Battery protocol detection supports:

- Legacy `BT-TH-*` names containing `BATT` or `BATTERY`
- Battery Pro names beginning with `RNGRBP` or `RNGC`
- RNGPRO-family names beginning with `RNGPRO`
- Battery Pro advertisements containing manufacturer ID `0xE14C`

## Architecture

The package is organized around these modules:

- `ble.py`: device wrapper, BLE sessions, request framing, retries, and
  device-specific read orchestration
- `register_map.py`: controller and DCC register definitions
- `parser.py`: shared register parsing plus controller and DCC parsers
- `renogy_parser.py`: public raw-response parser routing
- `battery.py`: battery protocol detection, commands, and frame parsers
- `shunt.py`: Smart Shunt notification client and payload parsing
- `__init__.py`: supported public API exports

`RenogyBleClient.read_device()` is the end-to-end entry point. It delegates
according to `RenogyBLEDevice.device_type` and returns a
`RenogyBleReadResult`.

`RenogyParser.parse()` is the lower-level entry point for callers that already
have a complete Modbus response:

```python
from renogy_ble import RenogyParser

parsed = RenogyParser.parse(
    raw_data,
    device_type="controller",
    register=0x0100,
)
```

The raw response must include the Modbus address, function code, byte count,
payload, and CRC.

## Data Contract

Successful reads return parsed values in a flat dictionary. Keys are stable
semantic names such as `battery_voltage`, `pv_power`, or
`total_power_generation`. Parsers apply the scaling, signedness, mapping, and
byte order defined by the relevant protocol implementation.

Multi-command controller and battery reads continue after an individual command
times out. If at least one command succeeds, `RenogyBleReadResult.success` is
`True` and `RenogyBleReadResult.error` is `None`, even though `parsed_data` may
be incomplete. No completeness flag is currently exposed; callers that require
a specific data set should validate the expected keys.

### DCC input power: verified RBC50D1S-G7 behavior

For `device_type="dcc"`, `RenogyBLEDevice.update_parsed_data()` normalizes
`0x0100` responses only when the cached `device_info` model is exactly
`RBC50D1S-G7`, ignoring case and surrounding whitespace:

| Returned key | Meaning on RBC50D1S-G7 |
| --- | --- |
| `alternator_power` | Reported alternator/DC-input power at `0x0106`, unchanged |
| `combined_input_power` | Reported combined solar and alternator input power at `0x0109` |
| `solar_power` | `max(0, combined_input_power - alternator_power)` |

If a partial response provides the combined total without alternator power,
normalization does not add a `solar_power` value from that response. The shared
DCC register map and the lower-level `RenogyParser.parse()` retain their existing
interpretation; the normalization requires the device wrapper's model metadata.

This scope follows the controlled tests and raw captures in
[renogy-ha issue #150](https://github.com/IAmTheMitchell/renogy-ha/issues/150#issuecomment-5635132622).
On the tested RBC50D1S-G7, an alternator-only capture reports 20 W at both
`0x0106` and `0x0109` with zero PV voltage/current. A combined-input capture
reports 74 W and 93 W respectively, consistent with about 19 W of solar input.
Solar-only behavior was separately reported; its regression frames are synthetic.

Testing is still needed for the rest of the RBC30D1S/RBC50D1S device families.
Reports of similar symptoms on other units do not identify their exact revisions,
so they do not establish that every family member uses the same register meaning.
Other revisions and unknown models retain the existing `solar_power` mapping and
do not gain `combined_input_power` through this normalization.

Before expanding the model guard, collect the exact model/revision, firmware
information when available, and raw `0x0100` responses for alternator-only,
solar-only, and combined-input operation. Include independent input measurements
or PV/alternator voltage and current to check the power interpretation, then add
captured-frame regression tests for each newly verified model. Synthetic frames
alone do not verify hardware semantics.

## Modbus Validation

Request helpers construct CRC-framed Modbus reads and writes. Response handling
validates the expected device ID, function code, payload length, and CRC before
parsing. Device-specific parsers may reject short or malformed frames rather
than returning misleading values.

## Extending Device Support

Choose the extension point based on the protocol:

1. Add controller-style registers to `register_map.py` and the appropriate
   parser in `parser.py`.
2. Add a dedicated module and read path when the device does not share the
   controller transport or response layout.
3. Export intentionally public helpers from `__init__.py`.
4. Add captured-frame parser tests and mocked BLE transport tests.
5. Update the supported-device documentation without claiming physical-device
   validation that was not performed.

Protocol, parsing, command framing, and BLE transport changes stay in this
repository. Home Assistant entities and discovery behavior stay in `renogy-ha`.

## Development and Validation

Use the project-scoped `uv` environment:

```bash
uv sync --all-groups
uv run ruff format .
uv run ruff check . --output-format=github
uv run ty check . --output-format=github
uv run pytest tests
```

Do not edit `CHANGELOG.md` or the project version manually; release automation
manages both.

## Packaging

The package is built from `pyproject.toml`, published to PyPI as `renogy-ble`,
and installed with:

```bash
pip install renogy-ble
```


## Optional controller metadata

Controller polls tolerate an unanswered `device_info` read by reconnecting before
reading the remaining commands. After three consecutive metadata timeouts on
polls that successfully parse PV telemetry, the library skips `device_info` for
one hour. It then probes again; another timeout with working telemetry starts
another one-hour cooldown. A successful metadata read or a poll without valid PV
telemetry resets the cooldown. State belongs to the device object and is reset
when that object is recreated. Other device families retain their existing reads.
