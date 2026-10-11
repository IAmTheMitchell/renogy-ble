# Device identification

`renogy_ble.identification` is a public, Home Assistant-independent module. Its
functions accept ordinary name, manufacturer-data, address, and model values.
They are also exported from `renogy_ble`.

```python
from renogy_ble import DeviceType, identify_advertisement

identity = identify_advertisement(
    "RNGPRO125BAT-EF036881",
    manufacturer_data={0xE14C: b""},
    address="14:9C:EF:03:68:81",
)
assert identity.device_type is DeviceType.BATTERY
assert identity.battery_variant == "rngpro"
```

## Result and precedence

`AdvertisementIdentity` is immutable and provides `supported`, `device_type`
(`DeviceType` or `None`), and `battery_variant` (`legacy`, `pro`, `rngpro`, or
`None`). It describes evidence, without selecting a caller's protocol.

| Evidence | Type | Battery variant |
| --- | --- | --- |
| `RNGRIU*`, `BTRIC*` | inverter | unresolved |
| `RTMShunt300*` | shunt300 | unresolved |
| `RNGPRO*` | battery | rngpro |
| `RNGRBP*`, `RNGC*` | battery | pro |
| Manufacturer ID `0xE14C` | battery | pro |
| `BT-TH-*` containing `BATT` or `BATTERY` | battery | legacy |
| Other `BT-TH-*` | unresolved, supported | unresolved |
| Missing or unsupported evidence | unresolved, unsupported | unresolved |

The table is ordered by precedence. Specific inverter/Shunt advertisements win
over conflicting battery manufacturer data, matching integration discovery.
The manufacturer ID wins over legacy markers, matching existing battery variant
selection. RNGPRO names win over the manufacturer ID because their current units
differ. Names are stripped of surrounding whitespace and prefixes are
case-sensitive; legacy suffix markers and DCC model matching ignore case.

`is_address_placeholder(name, address)` compares to the actual address, including
BlueZ colon-to-hyphen aliases and macOS UUIDs. Address-shaped strings are not
rejected merely for their shape. Manufacturer data remains usable when the name
is a placeholder. The classifier is stateless: applications must preserve prior
confirmed advertisements when later packets omit names or manufacturer data.

## Compatibility and consumer policy

`DeviceType` retains the string values `controller`, `dcc`, `battery`, `inverter`,
and `shunt300`. `name_matches_device_type` and
`expected_prefixes_for_device_type` check compatibility with a selected protocol;
a generic BT-TH name remains compatible with a manually selected battery,
controller, or DCC. It does not establish which hardware is attached.

`detect_device_type_from_model` retains the established DCC/RBC DC-input model
recognition and returns `None` for other models. It is a hint for applications,
not an instruction to change a protocol or a model profile. Shared prefix,
manufacturer, variant, and inverter-model constants live in this module.

Existing `battery.detect_battery_variant` and `is_supported_battery_name` remain
available and delegate to `identify_advertisement`; they also accept an optional
`address`. Existing battery constants and `ble.RIV4835CSH1S_MODEL` retain their
import locations. A contradictory inverter/Shunt name plus battery manufacturer
ID now has one classification in all consumers, rather than two incompatible
ones. No additional device family or write capability is introduced.

Battery transport classifies its protocol advertisement name before using its
cached variant. This lets a later RNGPRO name refine provisional manufacturer-only
Pro discovery, while hardware display names cannot change protocol scaling.
Manually selected generic BT-TH batteries retain their legacy fallback. Settings
capabilities retain their explicit type/profile allowlists and REGO name gate.

Home Assistant continues to own Bluetooth registration, config entries and user
selection, fallback labels, evidence caching, readiness, mismatch warnings, and
entity presentation. This library API has no Home Assistant dependency.
