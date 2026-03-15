# Renogy BLE

![Tests](https://github.com/IAmTheMitchell/renogy-ble/actions/workflows/test.yml/badge.svg)
![Release](https://github.com/IAmTheMitchell/renogy-ble/actions/workflows/release.yml/badge.svg)

A Python library for communicating with Renogy Bluetooth Low Energy (BLE) devices
and parsing their Modbus responses.

## Overview

Library for communicating with Renogy devices over BLE using BT-1 and BT-2
Bluetooth modules for controller-style devices, direct BLE notifications from
Smart Shunt 300 devices, and dedicated BLE reads for Renogy inverters.

Currently supported devices:

- Renogy charge controllers (such as Rover, Wanderer, Adventurer)
- Renogy Smart Shunt 300
- Renogy inverters that expose the RIV-series BLE register layout

Future planned support:

- Renogy batteries

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

### Smart Shunt 300 Reads

Smart Shunt 300 devices do not use the same Modbus command flow as Renogy
controllers. `device_type="shunt300"` is handled by a dedicated
notification-based client.

For one-off reads, `RenogyBleClient.read_device()` will automatically delegate to
the shunt client:

```python
import asyncio

from bleak import BleakScanner

from renogy_ble import RenogyBLEDevice, RenogyBleClient


async def main() -> None:
    devices = await BleakScanner.discover()
    ble_device = next(
        device for device in devices if (device.name or "").startswith("RTMShunt300")
    )

    renogy_device = RenogyBLEDevice(ble_device, device_type="shunt300")
    result = await RenogyBleClient().read_device(renogy_device)
    print(result.parsed_data)


if __name__ == "__main__":
    asyncio.run(main())
```

If you want the derived shunt energy totals to accumulate across repeated reads,
reuse a single `ShuntBleClient` instance:

```python
from renogy_ble import RenogyBLEDevice, ShuntBleClient

client = ShuntBleClient()
device = RenogyBLEDevice(ble_device, device_type="shunt300")
result = await client.read_device(device)
```

### Inverter Reads

Renogy inverters do not follow the same command flow as controller-style
devices. `device_type="inverter"` is handled by a dedicated client that:

- optionally reads an inverter-specific initialization characteristic
- subscribes to BLE notifications
- requests the default inverter command set
- parses the responses into a flat dictionary

For one-off reads, `RenogyBleClient.read_device()` automatically delegates to
`InverterBleClient`:

```python
import asyncio

from bleak import BleakScanner

from renogy_ble import RenogyBLEDevice, RenogyBleClient


async def main() -> None:
    devices = await BleakScanner.discover()
    ble_device = next(
        device for device in devices if (device.name or "").startswith("RNGRIU")
    )

    renogy_device = RenogyBLEDevice(ble_device, device_type="inverter")
    result = await RenogyBleClient().read_device(renogy_device)
    print(result.parsed_data)


if __name__ == "__main__":
    asyncio.run(main())
```

If you need direct control over the inverter transport, use
`InverterBleClient`:

```python
from renogy_ble import InverterBleClient, RenogyBLEDevice

client = InverterBleClient()
device = RenogyBLEDevice(ble_device, device_type="inverter")
result = await client.read_device(device)
```

The default inverter reads request these command groups:

- `main_data` from register `4000`
- `load_data` from register `4408`
- `device_id` from register `4109`
- `model` from register `4311`

### Custom Commands or Device IDs

You can supply your own Modbus command set or device ID if needed.
`RenogyBleClient` forwards inverter-specific overrides when it delegates to
`InverterBleClient`.

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

For inverter-specific customization, the package also exports the dedicated
defaults:

```python
from renogy_ble import INVERTER_COMMANDS, INVERTER_DEVICE_ID, InverterBleClient

client = InverterBleClient(
    device_id=INVERTER_DEVICE_ID,
    commands=INVERTER_COMMANDS,
)
```

## Features

- Connects to Renogy BLE devices and reads Modbus registers
- Connects to Renogy Smart Shunt 300 devices and parses BLE notifications
- Connects to supported Renogy inverters and reads BLE notification responses
- Builds Modbus read requests with CRC framing
- Parses raw BLE Modbus responses from Renogy devices
- Extracts controller, shunt, and inverter telemetry into a flat dictionary
- Returns data in a flat dictionary structure
- Applies scaling and mapping based on the register definitions

## Data Handling

### Input Format

The library accepts raw BLE Modbus response bytes and requires you to specify:

- The device type (for example, `device_type="controller"` or `device_type="inverter"`)
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
4. If the new device needs custom BLE behavior, add a dedicated client and delegate from `RenogyBleClient.read_device()`

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## References

[cyrils/renogy-bt](https://github.com/cyrils/renogy-bt/tree/main)

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.
