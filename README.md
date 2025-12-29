# Renogy BLE

![Tests](https://github.com/IAmTheMitchell/renogy-ble/actions/workflows/test.yml/badge.svg)
![Release](https://github.com/IAmTheMitchell/renogy-ble/actions/workflows/release.yml/badge.svg)

A Python library for communicating with Renogy Bluetooth Low Energy (BLE) devices
and parsing their Modbus responses.

## Overview

Library for communicating with Renogy devices over BLE using BT-1 and BT-2
Bluetooth modules, plus parsing raw Modbus response data into a flat dictionary.

Currently supported devices:

- Renogy charge controllers (such as Rover, Wanderer, Adventurer)

Future planned support:

- Renogy batteries
- Renogy inverters

## Installation

```bash
pip install renogy-ble
```

## Usage

There are two common ways to use this library:

- Parse raw Modbus response bytes (if you already handle BLE I/O elsewhere).
- Use the built-in BLE client to connect, read, and parse data end-to-end.

### Parse Raw Modbus Responses

Use this when you already have the raw Modbus response bytes and the register
address you requested.

```python
from renogy_ble import RenogyParser

# Raw BLE data received from your Renogy device
raw_data = b"\xff\x03\x02\x00\x04\x90S"  # Example data

# Parse the data for a specific model and register
parsed_data = RenogyParser.parse(raw_data, device_type="controller", register=57348)

# Use the parsed data
print(parsed_data)
# Example output: {'battery_type': 'lithium'}
```

Notes:

- `raw_data` must include the full Modbus response, including address, function
  code, byte count, and CRC.
- Parsed values may be scaled or mapped based on the register map (for example,
  voltages are scaled to volts).

### Connect Over BLE and Read Data

The `RenogyBleClient` handles Modbus framing, BLE notification reads, and parsing.
This example discovers a BLE device, connects, reads the default command set, and
prints the parsed data.

```python
import asyncio

from bleak import BleakScanner

from renogy_ble import RenogyBLEDevice, RenogyBleClient


async def main() -> None:
    devices = await BleakScanner.discover()
    ble_device = next(
        device for device in devices if "Renogy" in (device.name or "")
    )

    renogy_device = RenogyBLEDevice(ble_device, device_type="controller")
    client = RenogyBleClient()

    result = await client.read_device(renogy_device)
    if result.success:
        print(result.parsed_data)
    else:
        print(f"Read failed: {result.error}")


if __name__ == "__main__":
    asyncio.run(main())
```

### Custom Commands or Device IDs

You can supply your own Modbus command set or device ID if needed.

```python
from renogy_ble import COMMANDS, RenogyBleClient

custom_commands = {
    "controller": {
        **COMMANDS["controller"],
        "battery": (3, 57348, 1),
    }
}

client = RenogyBleClient(device_id=0xFF, commands=custom_commands)
```

## Features

- Connects to Renogy BLE devices and reads Modbus registers
- Builds Modbus read requests with CRC framing
- Parses raw BLE Modbus responses from Renogy devices
- Extracts information about battery, solar input, load output, controller status, and energy statistics
- Returns data in a flat dictionary structure
- Applies scaling and mapping based on the register definitions

## Data Handling

### Input Format

The library accepts raw BLE Modbus response bytes and requires you to specify:

- The device type (e.g., `device_type="controller"`)
- The register number being parsed (e.g., `register=256`)

### Output Format

Returns a flat dictionary of parsed values:

```python
{
    "battery_voltage": 12.9,
    "pv_power": 250,
    "charging_status": "mppt"  # Mapped from numeric values where applicable
}
```

## Extending for Other Models

The library is designed to be easily extensible for other Renogy device types. To add support for a new type:

1. Update the `REGISTER_MAP` in `register_map.py` with the new device type's register mapping
2. Create a new type-specific parser class in `parser.py` (if needed)
3. Update the `RenogyParser.parse()` method to route to your new parser

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## References

[cyrils/renogy-bt](https://github.com/cyrils/renogy-bt/tree/main)

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.
