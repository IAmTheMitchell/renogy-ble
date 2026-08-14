# Renogy Battery Usage

Supported Renogy batteries use a dedicated command set and parser. Set
`device_type="battery"`; the client detects the legacy, Battery Pro, or RNGPRO
protocol variant from the BLE advertisement.

Supported advertisements include:

- Legacy `BT-TH-*` names containing `BATT` or `BATTERY`
- Battery Pro names beginning with `RNGRBP` or `RNGC`
- RNGPRO-family names beginning with `RNGPRO`
- Battery Pro advertisements containing manufacturer ID `0xE14C`

## Discover and Read a Battery

```python
import asyncio

from bleak import BleakScanner

from renogy_ble import RenogyBLEDevice, RenogyBleClient, is_supported_battery_name


async def main() -> None:
    devices = await BleakScanner.discover(return_adv=True)
    ble_device, advertisement = next(
        (device, advertisement)
        for device, advertisement in devices.values()
        if is_supported_battery_name(
            device.name,
            manufacturer_data=advertisement.manufacturer_data,
        )
    )

    renogy_device = RenogyBLEDevice(
        ble_device,
        device_type="battery",
        manufacturer_data=advertisement.manufacturer_data,
        advertisement_name=advertisement.local_name,
    )
    result = await RenogyBleClient().read_device(renogy_device)
    if result.success:
        print(result.parsed_data)
    else:
        print(f"Read failed: {result.error}")


if __name__ == "__main__":
    asyncio.run(main())
```

Battery reads consist of multiple commands. If at least one command succeeds,
the result is successful even when another command times out, so
`parsed_data` may be incomplete. The library does not currently expose a
completeness flag; callers that require a specific data set should validate the
expected keys.
