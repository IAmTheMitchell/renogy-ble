# RIV4835CSH1S read-only LCD diagnostics

The optional `RenogyBleClient.read_inverter_diagnostics` API adds LCD settings,
fault-code slots, a raw warning word, and raw firmware fields. It does not alter
`read_device` or the existing settings write API. Consumers must explicitly
enable it, call it after a successful ordinary poll, and retain the returned
`riv_diagnostics` metadata for the next call:

```python
snapshot = await client.read_inverter_diagnostics(device, previous=previous)
previous = snapshot["riv_diagnostics"]
```

Only an inverter with `model_hint="RIV4835CSH1S"` is accepted. Field names, units,
and display precision are available from `get_inverter_diagnostic_fields`.
The method returns a separate snapshot without modifying `device.parsed_data`.

## LCD settings

These mappings use Renogy's telemetry aliases and SRNE native parameter
addresses. Readability and displayed values were checked on one RIV4835CSH1S
installation, with LCD firmware words **403 / 107**. This does not establish
compatibility with every firmware revision or validate every enum transition.
Raw enum values absent from a table are displayed as `Unknown (value)`.

| LCD | Reading | FC03 address | Scaling / observed value |
| --- | --- | --- | --- |
| 01 | Output priority | 4441 | enum; SBU |
| 02 | Output frequency | 4442 | /100 Hz; 60.00 |
| 03 | AC input voltage range | 4443 | enum; UPS |
| 04 | Battery to utility setpoint | 4437 | /10 V; 49.2 |
| 05 | Utility to battery setpoint | 4439 | /10 V; 53.6 |
| 06 | Battery charging mode | 4447 | enum; SnU |
| 07 | Maximum total charging current | 4422 | /10 A; 80.0 |
| 08 | Battery type | 4424 | enum; LF15 |
| 09 | Boost charge voltage | 4426 | /10 V; 54.0 |
| 10 | Boost charge duration | 4435 | minutes; 120 |
| 11 | Float charge voltage | 4427 | /10 V; 54.0 |
| 12 | Low voltage load disconnect | 4431 | /10 V; 44.8 |
| 13 | Overdischarge delay | 4433 | seconds; 30 |
| 14 | Low voltage warning | 4430 | /10 V; 49.6 |
| 15 | Discharge limit voltage | 4432 | /10 V; 42.8 |
| 17 | Equalization voltage | 4425 | /10 V; 54.0 |
| 18 | Equalization duration | 4434 | minutes; 0 |
| 19 | Equalization timeout | 4440 | minutes; 5 |
| 20 | Equalization interval | 4436 | days; 0 |
| 22 | Power saving mode | 4444 | enum; DIS |
| 23 | Overload automatic restart | 0xE20D | enum; ENA |
| 24 | Overtemperature automatic restart | 0xE20E | enum; ENA |
| 25 | Buzzer alarm | 4101 | enum; ENA |
| 26 | Mode transition alarm | 0xE211 | enum; ENA |
| 27 | Overload bypass | 0xE212 | enum; ENA |
| 35 | Low voltage disconnect recovery | 4429 | /10 V; 50.4 |
| 36 | PV charging current | 0xE001 | /10 A; 80.0 |
| 37 | Boost return setpoint | 4428 | /10 V; 50.8 |
| 38 | AC output voltage setting | 0xE208 | /10 V; 120.0 |

Programs 23, 24, 26, 27, 36, and 38 were explicitly compared with the physical
LCD after successful CRC-validated native reads. Program 28 already has ordinary
readback and a charging-current control at `0xE205`; it is not duplicated here.
Program 16 has a readable native candidate but was absent from this LCD, so it
is excluded. Program 21 requires a write/action; Program 29's mapping is
unresolved. Neither is read by this API.

Program 39 remains unresolved: both 4456 and `0xE21C` returned validated Modbus
exception 02. Register `0x0026` returned raw 51 with the LCD showing 20 A and is
not a confirmed current limit. This API includes no Program 39 sensor, probe,
or write. A readable setting must not be inferred from a menu number.

## Faults, warning word, and firmware

Four current fault-code slots occupy 4398–4401. All four must be readable before
the fault summary/count is available. Descriptions follow the RIV LCD manual;
unnamed codes remain `Unverified for this model`. The installation reported
four zeros. Nonzero fault descriptions are manual-based, not induced hardware
fault tests. Native fault bitmaps are a separate, unsubmitted research surface.

Warning register 4393 returned 50 (`0x0032`, zero-based bits 1, 4, and 5) in
different operating states. Generic protocol descriptions are not verified
for this model. The API preserves the raw mask and bits and displays
`Unverified (0x0032)`. Even a zero word does not certify a warning interpretation.

| Firmware field | Read | Observed result | Interpretation |
| --- | --- | --- | --- |
| Software Version Word 0x0014 | one word | 403 | Raw integer matching the LCD pair |
| Software Version Word 0x0015 | one word | 107 | Raw integer matching the LCD pair |
| SDK Firmware Text Candidate | 4319 / 0x10DF, eight words | `300*107*160*403` | Printable ASCII; component identities unverified |

Firmware words retain their raw decimal form. No dotted version formatting,
component labels, or authoritative device-info software version is inferred.

## Transport, cache, and evidence

Each call reads eight bounded ordinary diagnostic blocks and at most one extra
native/firmware block, using the client's existing session lock and inverter
device ID 32. Every request uses FC03, count at most 14, timeout two seconds,
and one attempt. The first nine successful ordinary polls complete the extra
read pass. Diagnostics add request/connection time and are intended for opt-in
monitoring rather than enforcing an AC circuit limit.

Native settings refresh at most every 900 seconds; successful firmware reads
are cached until the consumer resets `previous`. Unsupported blocks (validated
exception 02 or all-FFFF words) are not retried until that reset. Individual
FFFF settings are unavailable. Failures clear the attempted block's previous
values; a timeout, invalid frame, or bad CRC never becomes zero or a fresh
cached setting. Failed sessions are dropped to prevent late reply reuse.

`riv_diagnostics.fields` includes raw values, addresses, read status, sample and
attempt times, cache flags, and bounded response evidence. `pending` means the
extra pass is incomplete, `partial` means at least one block failed or was
unsupported, and `complete` means every planned block was read successfully.
This status describes reads, not complete model interpretation or warning
validation. Consumers should expose missing values as unavailable while
retaining their failure evidence.

## Sources

- [Renogy developer platform](https://platform.renogy.com/), including its
  [Inverter Modbus Protocol V1.0](https://renogy-website.oss-us-east-1.aliyuncs.com/DeveloperPlatform/Inverter_Modbus_Protocol_V1.0_EN.pdf).
- [SRNE V1.7 original protocol](https://github.com/RAR/esphome-srne-inverter/blob/c52bb3fb502f6a8e5099c475b2fccf0b7249b261/srne-hybrid-solar-inverter-modbus-protocol-v1-7.pdf)
  for native parameter layout, followed by model-specific LCD comparisons.
- RIV4835CSH1S LCD manual and installation comparisons recorded above. Generic
  warning definitions and other firmware's mappings are not certification for
  this model.
