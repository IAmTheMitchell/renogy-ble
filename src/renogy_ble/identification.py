"""Home Assistant-independent identification of supported Renogy devices.

A supported advertisement is not necessarily a known protocol profile. Generic
BT-TH modules can be attached to controllers, DCC chargers, or legacy batteries;
callers must retain their selected device type until stronger evidence exists.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Literal


class DeviceType(Enum):
    """Stable protocol identifiers accepted by RenogyBLEDevice."""

    CONTROLLER = "controller"
    BATTERY = "battery"
    INVERTER = "inverter"
    DCC = "dcc"
    SHUNT300 = "shunt300"


RENOGY_BT_PREFIX = "BT-TH-"
RENOGY_INVERTER_PREFIX = "RNGRIU"
RENOGY_REGO_INVERTER_PREFIX = "BTRIC"
SHUNT300_BT_PREFIX = "RTMShunt300"
RIV4835CSH1S_MODEL = "RIV4835CSH1S"
BATTERY_DEVICE_TYPE = DeviceType.BATTERY.value
BATTERY_VARIANT_LEGACY = "legacy"
BATTERY_VARIANT_PRO = "pro"
# RNGPRO uses 0.01 A rather than Pro's 0.1 A; RNGRBP/RNGPRO cell units
# are 0.1 V, while RNGC units remain unconfirmed.
BATTERY_VARIANT_RNGPRO = "rngpro"
BatteryVariant = Literal["legacy", "pro", "rngpro"]
BATTERY_RNGRBP_NAME_PREFIX = "RNGRBP"
BATTERY_RNGC_NAME_PREFIX = "RNGC"
BATTERY_PRO_NAME_PREFIXES = (BATTERY_RNGRBP_NAME_PREFIX, BATTERY_RNGC_NAME_PREFIX)
BATTERY_RNGPRO_NAME_PREFIXES = ("RNGPRO",)
RENOGY_BATTERY_PRO_PREFIXES = (
    *BATTERY_PRO_NAME_PREFIXES,
    *BATTERY_RNGPRO_NAME_PREFIXES,
)
BATTERY_LEGACY_NAME_PREFIX = RENOGY_BT_PREFIX
BATTERY_LEGACY_NAME_MARKERS = ("BATT", "BATTERY")
BATTERY_PRO_MANUFACTURER_ID = 0xE14C
SUPPORTED_BLE_NAME_PREFIXES = (
    RENOGY_BT_PREFIX,
    RENOGY_INVERTER_PREFIX,
    RENOGY_REGO_INVERTER_PREFIX,
    *RENOGY_BATTERY_PRO_PREFIXES,
    SHUNT300_BT_PREFIX,
)
_DEVICE_NAME_PREFIXES_BY_TYPE = {
    DeviceType.CONTROLLER.value: (RENOGY_BT_PREFIX,),
    DeviceType.DCC.value: (RENOGY_BT_PREFIX,),
    DeviceType.BATTERY.value: (RENOGY_BT_PREFIX, *RENOGY_BATTERY_PRO_PREFIXES),
    DeviceType.INVERTER.value: (RENOGY_INVERTER_PREFIX, RENOGY_REGO_INVERTER_PREFIX),
    DeviceType.SHUNT300.value: (SHUNT300_BT_PREFIX,),
}
_DCC_MODEL_PATTERN = re.compile(r"^(DCC|RBC\d+D)", re.IGNORECASE)


@dataclass(frozen=True)
class AdvertisementIdentity:
    """Classification without selecting or overriding a caller's protocol.

    ``supported=True, device_type=None`` identifies an ambiguous BT-TH module.
    ``supported=False`` means there is no supported evidence in this packet.
    Manufacturer-only battery discovery establishes Pro, not RNGPRO scaling.
    """

    supported: bool = False
    device_type: DeviceType | None = None
    battery_variant: BatteryVariant | None = None


def is_address_placeholder(name: str | None, address: str | None) -> bool:
    """Compare with the actual address, including BlueZ aliases and macOS UUIDs."""
    if not isinstance(name, str) or not address:
        return False
    normalized = address.strip().casefold()
    return name.strip().casefold() in (normalized, normalized.replace(":", "-"))


def _usable_name(name: str | None, address: str | None = None) -> str:
    if not isinstance(name, str) or is_address_placeholder(name, address):
        return ""
    return name.strip()


def identify_advertisement(
    name: str | None,
    *,
    manufacturer_data: Mapping[int, bytes] | None = None,
    address: str | None = None,
) -> AdvertisementIdentity:
    """Identify ordinary advertisement values using shared family precedence.

    Specific inverter/Shunt names win over conflicting manufacturer data.
    Battery names identify RNGPRO or Pro before manufacturer data; the Pro ID
    wins over legacy markers, preserving the battery transport's variant rule.
    Generic BT-TH names alone never establish controller versus DCC hardware.
    Names remain case-sensitive, matching device advertisements.
    """
    name = _usable_name(name, address)
    if name.startswith((RENOGY_INVERTER_PREFIX, RENOGY_REGO_INVERTER_PREFIX)):
        return AdvertisementIdentity(True, DeviceType.INVERTER)
    if name.startswith(SHUNT300_BT_PREFIX):
        return AdvertisementIdentity(True, DeviceType.SHUNT300)
    if name.startswith(BATTERY_RNGPRO_NAME_PREFIXES):
        variant = BATTERY_VARIANT_RNGPRO
    elif name.startswith(BATTERY_PRO_NAME_PREFIXES):
        variant = BATTERY_VARIANT_PRO
    elif BATTERY_PRO_MANUFACTURER_ID in (manufacturer_data or {}):
        variant = BATTERY_VARIANT_PRO
    elif name.startswith(BATTERY_LEGACY_NAME_PREFIX) and any(
        marker in name[len(BATTERY_LEGACY_NAME_PREFIX) :].upper()
        for marker in BATTERY_LEGACY_NAME_MARKERS
    ):
        variant = BATTERY_VARIANT_LEGACY
    else:
        return AdvertisementIdentity(supported=name.startswith(RENOGY_BT_PREFIX))
    return AdvertisementIdentity(True, DeviceType.BATTERY, variant)


def expected_prefixes_for_device_type(device_type: str) -> tuple[str, ...]:
    """Return family prefixes compatible with a caller-selected protocol."""
    return _DEVICE_NAME_PREFIXES_BY_TYPE.get(device_type, (RENOGY_BT_PREFIX,))


def name_matches_device_type(
    name: str | None, device_type: str, *, address: str | None = None
) -> bool:
    """Test name compatibility, without inferring or changing the selected type.

    Generic BT-TH names remain compatible with a selected legacy battery,
    controller, or DCC protocol. This is not proof of the attached hardware.
    Manufacturer-only evidence does not establish a compatible name.
    """
    name = _usable_name(name, address)
    return bool(name) and name.startswith(
        expected_prefixes_for_device_type(device_type)
    )


def detect_device_type_from_model(model: str | None) -> str | None:
    """Return DCC for established model families, otherwise leave it unresolved.

    DCC30S/DCC50S and RBC20D1U/RBC30D1S/RBC50D1S(-G6) identify DC input.
    This deliberately preserves the existing model-warning contract; other
    models do not select a protocol or override an explicitly chosen profile.
    """
    if isinstance(model, str) and _DCC_MODEL_PATTERN.match(model.strip()):
        return DeviceType.DCC.value
    return None
