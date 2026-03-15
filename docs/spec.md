# Renogy BLE Developer Specification

## Overview

`renogy-ble` is a standalone Python library for communicating with supported
Renogy Bluetooth Low Energy devices and parsing their responses into usable
Python data structures. The library is intentionally independent of Home
Assistant so it can be reused by other projects.

The current implementation includes both transport helpers and parsing logic:

- Modbus framing for controller-style devices.
- Dedicated notification-driven clients for Smart Shunt 300 devices.
- Dedicated notification-driven clients for supported Renogy inverters.
- A shared register-map-based parsing pipeline that returns flat dictionaries.

## Supported Devices

### Controller-style devices

- Renogy charge controllers that communicate through BT-1 or BT-2 modules.
- DCC devices that use the controller-style Modbus transport.

### Direct BLE devices

- Renogy Smart Shunt 300 devices.
- Renogy inverters that expose the RIV-series BLE register layout.

## Library Responsibilities

The library is responsible for:

- discovering and connecting to supported Renogy BLE devices when the built-in
  clients are used
- building Modbus read and write frames, including CRC handling
- collecting notification payloads from device-specific transports
- parsing raw responses with device-type-specific register definitions
- returning flat dictionaries with scaled and mapped values where configured

The library is not responsible for:

- Home Assistant entity management
- persistence, scheduling, or long-term storage
- application-specific retry policy outside the device clients provided here

## Architecture

### Package structure

```text
src/renogy_ble/
  __init__.py
  ble.py
  inverter.py
  parser.py
  register_map.py
  renogy_parser.py
  shunt.py
tests/
  test_ble.py
  test_parser.py
  test_shunt.py
```

### Core components

#### `ble.py`

- Defines shared BLE constants and default controller/DCC/inverter command maps.
- Implements Modbus request builders.
- Provides `RenogyBLEDevice`.
- Provides `RenogyBleClient`, which reads controller-style devices directly and
  delegates `shunt300` and `inverter` devices to dedicated clients.

#### `inverter.py`

- Implements `InverterBleClient`.
- Uses inverter-specific defaults such as `INVERTER_DEVICE_ID`,
  `INVERTER_INIT_CHAR_UUID`, and `INVERTER_COMMANDS`.
- Reads the initialization characteristic when available, subscribes to
  notifications, sends inverter requests, and parses each response into the
  device state.

#### `shunt.py`

- Implements the Smart Shunt 300 transport and derived metric handling.

#### `register_map.py`

- Defines register metadata by device type.
- Includes controller, DCC, and inverter register layouts.
- Supports scaling, byte order, string fields, and mapped values.

#### `parser.py`

- Provides `RenogyBaseParser` plus device-type-specific parsers.
- Current parser classes include `ControllerParser`, `DCCParser`, and
  `InverterParser`.

#### `renogy_parser.py`

- Routes parse requests by `device_type`.
- Returns `{}` for unsupported device types.

## Device Flows

### Controller and DCC flow

1. Connect to the device over BLE.
2. Subscribe to the standard Renogy read characteristic.
3. Send Modbus requests over the write characteristic.
4. Collect notification bytes until the expected response length is reached.
5. Parse the response for the requested register.

### Smart Shunt 300 flow

1. Connect using the shunt-specific BLE flow.
2. Consume direct notification payloads.
3. Parse shunt data and derived totals.

### Inverter flow

1. Connect using `InverterBleClient`.
2. Attempt to read the inverter initialization characteristic.
3. Subscribe to the standard Renogy read characteristic.
4. Send the default inverter command set:
   - `main_data` at register `4000`
   - `load_data` at register `4408`
   - `device_id` at register `4109`
   - `model` at register `4311`
5. Parse each successful response and merge it into the device state.

## Public API

The package exports the shared BLE and parsing entry points plus device-specific
helpers:

- `RenogyBleClient`
- `RenogyBLEDevice`
- `RenogyParser`
- `ShuntBleClient`
- `InverterBleClient`
- `COMMANDS`
- `INVERTER_COMMANDS`
- `DEFAULT_DEVICE_ID`
- `INVERTER_DEVICE_ID`
- `INVERTER_INIT_CHAR_UUID`

## Data Handling

### Input requirements

Raw parser calls require:

- the full Modbus response frame, including address, function code, byte count,
  payload, and CRC
- a `device_type`
- the starting register for the response

### Output format

Parsers return a flat dictionary. Values may be:

- scaled numeric values such as volts, amps, or hertz
- mapped string values for enumerations
- decoded strings for text registers such as inverter model identifiers

Example output:

```python
{
    "battery_voltage": 40.0,
    "ac_output_voltage": 230.0,
    "load_active_power": 500,
    "model": "RIV1220PU-126",
}
```

## Error Handling

The current implementation follows these rules:

- connection failures return an unsuccessful read result with the underlying
  exception attached
- short or malformed responses are logged and skipped when possible
- partial parsing is allowed when enough data exists for individual fields
- unsupported device types return empty parse results
- inverter reads succeed when at least one configured command is parsed

## Extensibility

To add support for a new device type:

1. Add register definitions to `register_map.py`.
2. Add or extend a parser in `parser.py`.
3. Route the new type in `renogy_parser.py`.
4. If the transport differs from controller-style Modbus reads, add a dedicated
   BLE client and delegate to it from `RenogyBleClient.read_device()`.
5. Add unit tests that cover transport behavior and parsing.

## Verification Expectations

Changes should be validated with the repository standard workflow:

1. `uv run ruff format .`
2. `uv run ruff check . --output-format=github`
3. `uv run ty check . --output-format=github`
4. `uv run pytest tests`

All four steps should pass in a single run before changes are considered ready.
