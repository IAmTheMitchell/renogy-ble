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

The allowlists migrate the controls previously exposed by renogy-ha; readable
registers do not automatically become writable. No battery, Shunt or
Communication Hub settings are exposed. Unknown inverter profiles have no
settings. REGO retains its established `BTRIC` advertisement-name gate with no
model hint. `model_hint="RIV4835CSH1S"` selects only the RIV control, irrespective
of its Bluetooth module's advertised name.

| Profile | Key | Native values |
| --- | --- | --- |
| DCC and controller | `battery_type` | `custom`, `open`, `sealed`, `gel`, `lithium` |
| Controller | `load_enabled` | `True` or `False` |
| DCC | `max_charging_current` | 10, 20, 30, 40, 50, 60 A |
| DCC | `overvoltage_threshold`, `charging_limit_voltage`, `equalization_voltage`, `boost_voltage`, `float_voltage`, `boost_return_voltage`, `overdischarge_return_voltage`, `undervoltage_warning`, `overdischarge_voltage`, `discharge_limit_voltage` | 7–17 V, 0.1 V steps |
| DCC | `reverse_charging_voltage` | 11–15 V, 0.1 V steps |
| DCC | `overdischarge_delay` | 0–120 seconds, integer |
| DCC | `equalization_time` | 0–300 minutes, integer |
| DCC | `boost_time` | 10–300 minutes, integer |
| DCC | `equalization_interval` | 0–255 days, integer |
| DCC | `temperature_compensation` | 0–5 mV/C/2V, integer |
| DCC | `solar_cutoff_current` | 0–10 A, 0.01 A precision |
| REGO | `inverter_ac_input_current_limit` | 1–50 A, 1 A steps |
| REGO | `inverter_charge_current` | 5–150 A, 5 A steps |
| REGO | `inverter_low_voltage_warn` | 9–15.5 V, 0.1 V steps |
| REGO | `inverter_over_voltage` | 9–16 V, 0.1 V steps |
| RIV4835CSH1S | `inverter_ac_charge_current` | 0–40 A, 5 A steps |

Bounds preserve existing conservative integration limits. They are not newly
verified hardware limits for every model. Solar cutoff preserves the existing
centiamp precision; HA can still present its existing 1 A input step. DCC/controller
register offsets, scaling and enum codes come from the existing read parser's
fields. In particular, the library encodes `custom` as 0 on DCC and 5 on controllers.
Inverter reads and writes share their setpoint register and precision definitions.

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

## Release

This API is an unpublished candidate based on release 2.9.0; it is not available
in the released 2.9.0 package. Release automation must publish the library change
before consumers adopt a final released dependency pin. Tests cover serialized
requests, profile gating, precision, and acknowledgement errors with mocked GATT;
no new live-hardware validation was performed during this migration.
