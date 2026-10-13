# Device settings

`RenogyBleClient.write_setting(device, key, value)` accepts a semantic setting key
and a value in native units. It returns `RenogyBleWriteResult`, just like
`write_single_register`. Invalid or unsupported settings return `success=False`
with a `ValueError` before any BLE connection. Transport and Modbus errors are
returned in `error`.

```python
from renogy_ble import RenogyBleClient, get_device_settings

client = RenogyBleClient()
# device is a RenogyBLEDevice with its configured device_type/model_hint.
result = await client.write_setting(device, "battery_type", "custom")
if not result.success:
    print(result.error)

capabilities = get_device_settings(
    device.device_type,
    model_hint=device.model_hint,
    advertisement_name=device.advertised_name,
)
```

Capabilities are immutable `DeviceSetting` values with a `key`, `kind`, native
`minimum`, `maximum`, `step` and `options`. They contain no register addresses or
wire scaling. `SettingValue` is the public value type. Boolean settings require a
boolean, choice settings require one of their options, and numeric settings
require a finite number within the stated bounds and steps. Decimal conversion
rejects unrepresentable precision instead of truncating a binary float.

## Supported profiles and values

The allowlists include the existing controls and controller charging parameters; readable
registers do not automatically become writable. No battery, Shunt or
Communication Hub settings are exposed. Unknown inverter profiles have no
settings. REGO retains its established `BTRIC` advertisement-name gate with no
model hint. `model_hint="RIV4835CSH1S"` selects the RIV controls, irrespective
of its Bluetooth module's advertised name.

| Profile | Key | Native values |
| --- | --- | --- |
| DCC and controller | `battery_type` | `custom`, `open`, `sealed`, `gel`, `lithium` |
| Controller | `load_enabled` | `True` or `False` |
| DCC | `max_charging_current` | 10, 20, 30, 40, 50, 60 A |
| DCC and controller | `overvoltage_threshold`, `charging_limit_voltage`, `equalization_voltage`, `boost_voltage`, `float_voltage`, `boost_return_voltage`, `overdischarge_return_voltage`, `undervoltage_warning`, `overdischarge_voltage`, `discharge_limit_voltage` | 7–17 V, 0.1 V steps |
| DCC | `reverse_charging_voltage` | 11–15 V, 0.1 V steps |
| DCC and controller | `overdischarge_delay` | 0–120 seconds, integer |
| DCC and controller | `equalization_time` | 0–300 minutes, integer |
| DCC and controller | `boost_time` | 10–300 minutes, integer |
| DCC and controller | `equalization_interval` | 0–255 days, integer |
| DCC and controller | `temperature_compensation` | 0–5 mV/C/2V, integer |
| DCC | `solar_cutoff_current` | 0–10 A, 0.01 A precision |
| REGO | `inverter_ac_input_current_limit` | 1–50 A, 1 A steps |
| REGO | `inverter_charge_current` | 5–150 A, 5 A steps |
| REGO | `inverter_low_voltage_warn` | 9–15.5 V, 0.1 V steps |
| REGO | `inverter_over_voltage` | 9–16 V, 0.1 V steps |
| RIV4835CSH1S | `inverter_ac_charge_current` | 0–40 A, 5 A steps |
| RIV4835CSH1S | `output_priority` | `SOL`, `UTI`, `SBU` |

Bounds preserve existing conservative integration limits. They are not newly
verified hardware limits for every model. Solar cutoff preserves the existing
centiamp precision; HA can still present its existing 1 A input step. DCC/controller
register offsets, scaling and enum codes come from the existing read parser's
fields. In particular, the library encodes `custom` as 0 on DCC and 5 on controllers.
Inverter reads and writes share their setting definitions. RIV4835CSH1S Program
01 output priority is hardware-validated at register `0x1159`, with raw values
`0=SOL`, `1=UTI`, and `2=SBU`. Ordinary inverter polling provides authoritative
readback after writes. An unknown Program 01 raw value omits `output_priority`
from the result and clears any previously cached mode.

## Acknowledgement and addressing

Success confirms an FC06 acknowledgement echoing the target address, register and
encoded value with a valid CRC. It does **not** establish persistent storage or
that firmware retained a setting: presets can restore values. A later ordinary
poll is authoritative readback. Callers control refresh scheduling and may show
an optimistic value after a successful acknowledgement.

The default client now writes to inverter address `0x20` for inverter devices and
`0xFF` for other devices. An explicit `RenogyBleClient(device_id=...)` overrides
write addressing, including an explicitly supplied `0xFF`. Address selection is
per transaction, so one client can serve different devices without mutating its
configured address. Existing low-level `write_register` and
`write_single_register` signatures and result types remain available. This change
does not alter Hub addressing or add Hub writes.

## Controller charging parameters and release

Controller charging-parameter writes are an unpublished extension to the settings
API in 2.11.0. Consumers must wait for a library release before pinning a version
with these capabilities. The controller supports the 15 charging parameters in
the table; DCC-only reverse charging voltage, maximum charging current and solar
cutoff current remain unsupported on controllers.

These controls retain conservative application bounds shared with DCC controls,
not newly verified hardware limits. Renogy presets manage their own voltage
table. Select `custom` before changing charging voltages, check every value
against the battery datasheet, and confirm subsequent device readback. Changing
the battery preset can itself load firmware defaults; an acknowledgement does
not prove that the bank is charging safely or that a value was retained.

Tests cover serialized requests, profile gating, precision and acknowledgement
errors with mocked GATT. No independent live-hardware validation was performed.

Controller `system_voltage` readback normalizes the auto-detection sentinel to
`"auto"`; fixed nominal voltages remain integers. Previously auto-detection was
returned as the raw integer 255. DCC system-voltage readback is unchanged.
