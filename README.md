# Renogy BLE

![Tests](https://github.com/IAmTheMitchell/renogy-ble/actions/workflows/test.yml/badge.svg)
![Release](https://github.com/IAmTheMitchell/renogy-ble/actions/workflows/release.yml/badge.svg)

A Python library for parsing Bluetooth Low Energy (BLE) data from Renogy devices.

## Overview

Library for parsing raw BLE Modbus data from Renogy devices with BT-1 and BT-2 Bluetooth modules.

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

Basic usage example:

```python
from renogy_ble import RenogyParser

# Raw BLE data received from your Renogy device
raw_data = b"\xff\x03\x02\x00\x04\x90S"  # Example data

# Parse the data for a specific model and register
parsed_data = RenogyParser.parse(raw_data, type="controller", register=57348)

# Use the parsed data
print(parsed_data)
# Example output: {'battery_type': 'lithium'}
```

## Features

- Parses raw BLE Modbus data from Renogy devices
- Extracts information about battery, solar input, load output, controller status, and energy statistics
- Returns data in a flat dictionary structure
- Returns raw values (no scaling or unit conversion)

## Data Handling

### Input Format

The library accepts raw BLE Modbus response bytes and requires you to specify:

- The device type (e.g., `type="controller"`)
- The register number being parsed (e.g., `register=256`)

### Output Format

Returns a flat dictionary of raw values:

```python
{
    "battery_voltage": 129,
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
