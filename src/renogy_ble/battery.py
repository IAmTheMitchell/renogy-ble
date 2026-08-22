"""Helpers for Renogy battery protocol detection and parsing."""

from __future__ import annotations

from functools import cache
from typing import Any, Literal

BATTERY_DEVICE_TYPE = "battery"
BATTERY_VARIANT_LEGACY = "legacy"
BATTERY_VARIANT_PRO = "pro"
# RNGPRO-family batteries (e.g. RBT12500LFP-SHBT) share the Pro register map and
# device id but use 0.01 A current units rather than the Pro variant's 0.1 A.
# Their 0.1 V cell units match RNGRBP; RNGC scaling remains unconfirmed.
BATTERY_VARIANT_RNGPRO = "rngpro"
BatteryVariant = Literal["legacy", "pro", "rngpro"]
BatteryCellVoltageDivisor = Literal[10, 1000]

BATTERY_RNGRBP_NAME_PREFIX = "RNGRBP"
BATTERY_PRO_NAME_PREFIXES = (BATTERY_RNGRBP_NAME_PREFIX, "RNGC")
BATTERY_RNGPRO_NAME_PREFIXES = ("RNGPRO",)
BATTERY_LEGACY_NAME_PREFIX = "BT-TH-"
BATTERY_LEGACY_NAME_MARKERS = ("BATT", "BATTERY")
BATTERY_PRO_MANUFACTURER_ID = 0xE14C

BATTERY_PROTOCOL_DEVICE_IDS: dict[BatteryVariant, int] = {
    BATTERY_VARIANT_LEGACY: 0x30,
    BATTERY_VARIANT_PRO: 0xFF,
    BATTERY_VARIANT_RNGPRO: 0xFF,
}

BATTERY_DEFAULT_MODELS: dict[BatteryVariant, str] = {
    BATTERY_VARIANT_LEGACY: "Renogy Bluetooth Battery",
    BATTERY_VARIANT_PRO: "Renogy BT Battery Pro",
    BATTERY_VARIANT_RNGPRO: "Renogy BT Battery Pro",
}

# Format: (register, word_count)
BATTERY_COMMANDS: dict[str, tuple[int, int]] = {
    "device_info": (0x13F0, 0x1C),
    "pack_status": (0x13B2, 0x07),
    "cell_status": (0x1388, 0x22),
    "mosfet_status": (0x13EC, 0x08),
}

HUB_BATTERY_PACK_STATUS_REGISTER = 0x13B2
HUB_BATTERY_PACK_STATUS_WORD_COUNT = 0x06


def clean_battery_text(value: bytes) -> str:
    """Decode ASCII battery metadata and strip padding."""
    return value.decode("ascii", errors="ignore").strip("\x00").strip()


def is_rngr_bp_battery_name(name: str | None) -> bool:
    """Return whether an advertisement belongs to the RNGRBP family."""
    return (name or "").strip().startswith(BATTERY_RNGRBP_NAME_PREFIX)


def battery_cell_voltage_divisor(
    name: str | None,
    *,
    variant: BatteryVariant,
) -> BatteryCellVoltageDivisor | None:
    """Return a confirmed cell-voltage divisor, if the family identifies one."""
    if variant == BATTERY_VARIANT_RNGPRO or is_rngr_bp_battery_name(name):
        return 10
    if variant != BATTERY_VARIANT_PRO or (name or "").strip().startswith("RNGC"):
        return 1000
    return None


def detect_battery_variant(
    name: str | None,
    *,
    manufacturer_data: dict[int, bytes] | None = None,
) -> BatteryVariant | None:
    """Return the supported battery protocol variant for the given advertisement."""
    cleaned_name = (name or "").strip()
    manufacturer_data = manufacturer_data or {}

    if cleaned_name.startswith(BATTERY_RNGPRO_NAME_PREFIXES):
        return BATTERY_VARIANT_RNGPRO

    if cleaned_name.startswith(BATTERY_PRO_NAME_PREFIXES):
        return BATTERY_VARIANT_PRO

    if BATTERY_PRO_MANUFACTURER_ID in manufacturer_data:
        return BATTERY_VARIANT_PRO

    if _is_legacy_battery_name(cleaned_name):
        return BATTERY_VARIANT_LEGACY

    return None


def is_supported_battery_name(
    name: str | None,
    *,
    manufacturer_data: dict[int, bytes] | None = None,
) -> bool:
    """Return True when an advertisement matches a supported battery family."""
    return detect_battery_variant(name, manufacturer_data=manufacturer_data) is not None


def _is_legacy_battery_name(name: str) -> bool:
    """Return True only for legacy battery advertisements, not shared BT-TH devices."""
    if not name.startswith(BATTERY_LEGACY_NAME_PREFIX):
        return False

    suffix = name[len(BATTERY_LEGACY_NAME_PREFIX) :].upper()
    return any(marker in suffix for marker in BATTERY_LEGACY_NAME_MARKERS)


@cache
def build_battery_command(
    variant: BatteryVariant,
    register: int,
    word_count: int,
    device_id: int | None = None,
) -> bytes:
    """Build a battery read request, optionally targeting a specific device ID."""
    target_device_id = (
        BATTERY_PROTOCOL_DEVICE_IDS[variant] if device_id is None else device_id
    )
    frame = bytearray(
        [
            target_device_id,
            0x03,
            (register >> 8) & 0xFF,
            register & 0xFF,
            (word_count >> 8) & 0xFF,
            word_count & 0xFF,
        ]
    )
    crc_low, crc_high = modbus_crc(frame)
    frame.extend([crc_low, crc_high])
    return bytes(frame)


def modbus_crc(data: bytes | bytearray) -> tuple[int, int]:
    """Calculate the Modbus CRC16 of the given data."""
    crc = 0xFFFF
    for pos in data:
        crc ^= pos
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return (crc & 0xFF, (crc >> 8) & 0xFF)


def parse_battery_device_info(
    data: bytes,
    *,
    variant: BatteryVariant,
) -> dict[str, Any]:
    """Parse the battery metadata frame."""
    parsed: dict[str, Any] = {
        "battery_variant": variant,
        "model": BATTERY_DEFAULT_MODELS[variant],
    }

    serial_number = clean_battery_text(data[15:31])
    if serial_number:
        parsed["serial_number"] = serial_number

    battery_name = clean_battery_text(data[39:55])
    if battery_name:
        parsed["device_name"] = battery_name

    sw_version = clean_battery_text(data[55:59])
    if sw_version:
        parsed["sw_version"] = sw_version

    return parsed


def parse_battery_pack_status(
    data: bytes,
    *,
    variant: BatteryVariant,
) -> dict[str, Any]:
    """Parse the battery summary status frame."""
    current_scale = 0.1 if variant == BATTERY_VARIANT_PRO else 0.01
    battery_voltage = int.from_bytes(data[5:7], byteorder="big") / 10
    battery_current = int.from_bytes(data[3:5], byteorder="big", signed=True) / (
        10 if variant == BATTERY_VARIANT_PRO else 100
    )
    battery_remaining_capacity = int.from_bytes(data[7:11], byteorder="big") / 1000
    battery_capacity = int.from_bytes(data[11:15], byteorder="big") / 1000
    battery_cycle_count = int.from_bytes(data[15:17], byteorder="big")

    parsed: dict[str, Any] = {
        "battery_variant": variant,
        "battery_voltage": round(battery_voltage, 1),
        "battery_current": round(battery_current, 2 if current_scale == 0.01 else 1),
        "battery_remaining_capacity": round(battery_remaining_capacity, 3),
        "battery_capacity": battery_capacity,
        "battery_cycle_count": battery_cycle_count,
        "battery_power": round(battery_voltage * battery_current, 3),
    }

    if battery_capacity > 0:
        parsed["battery_percentage"] = round(
            (battery_remaining_capacity / battery_capacity) * 100, 1
        )

    return parsed


def parse_hub_battery_pack_status(data: bytes) -> dict[str, Any]:
    """Parse the validated read-only Communication Hub battery status frame."""
    expected_length = 3 + (HUB_BATTERY_PACK_STATUS_WORD_COUNT * 2) + 2
    if len(data) < expected_length or data[2] < HUB_BATTERY_PACK_STATUS_WORD_COUNT * 2:
        return {}

    battery_current = int.from_bytes(data[3:5], byteorder="big", signed=True) / 100
    battery_voltage = int.from_bytes(data[5:7], byteorder="big") / 10
    battery_remaining_capacity = int.from_bytes(data[7:11], byteorder="big") / 1000
    battery_capacity = int.from_bytes(data[11:15], byteorder="big") / 1000

    parsed: dict[str, Any] = {
        "slave_id": data[0],
        "battery_voltage": round(battery_voltage, 1),
        "battery_current": round(battery_current, 2),
        "battery_power": round(battery_voltage * battery_current, 3),
        "battery_remaining_capacity": round(battery_remaining_capacity, 3),
        "battery_capacity": battery_capacity,
    }

    if battery_capacity > 0:
        parsed["battery_percentage"] = round(
            (battery_remaining_capacity / battery_capacity) * 100, 1
        )

    return parsed


def parse_battery_cell_status(
    data: bytes,
    *,
    variant: BatteryVariant,
    cell_voltage_divisor: BatteryCellVoltageDivisor | None = None,
) -> dict[str, Any]:
    """Parse cell voltages and temperature sensors."""
    parsed: dict[str, Any] = {}

    cell_count = int.from_bytes(data[3:5], byteorder="big")
    parsed["cell_count"] = cell_count

    raw_cell_values = [
        int.from_bytes(data[start : start + 2], byteorder="big")
        for start in range(5, 5 + min(cell_count, 16) * 2, 2)
    ]
    cell_divisor = cell_voltage_divisor or battery_cell_voltage_divisor(
        None, variant=variant
    )
    if cell_divisor is None:
        # Manufacturer-only discovery does not identify whether a Pro pack is
        # RNGRBP (0.1 V units) or RNGC (millivolts). A positive raw value below
        # 100 would be under 0.1 V with millivolt encoding, so infer only that
        # unambiguous case and preserve the millivolt default otherwise.
        positive_values = [value for value in raw_cell_values if value > 0]
        cell_divisor = 10 if positive_values and max(positive_values) < 100 else 1000
    cell_values = [value / cell_divisor for value in raw_cell_values]
    if cell_values:
        parsed["cell_voltages"] = cell_values
        parsed["cell_voltage_min"] = min(cell_values)
        parsed["cell_voltage_max"] = max(cell_values)
        parsed["cell_voltage_delta"] = round(max(cell_values) - min(cell_values), 3)

    temp_sensor_count = int.from_bytes(data[37:39], byteorder="big")
    parsed["battery_temperature_sensors"] = temp_sensor_count

    temp_values = [
        int.from_bytes(data[start : start + 2], byteorder="big", signed=True) / 10
        for start in range(39, 39 + min(temp_sensor_count, 16) * 2, 2)
    ]
    if temp_values:
        parsed["battery_temperature_values"] = temp_values
        parsed["battery_temperature"] = round(sum(temp_values) / len(temp_values), 1)
        parsed["battery_temperature_min"] = min(temp_values)
        parsed["battery_temperature_max"] = max(temp_values)

    return parsed


def parse_battery_mosfet_status(
    data: bytes,
    *,
    variant: BatteryVariant,
) -> dict[str, Any]:
    """Parse fault and MOSFET flags."""
    parsed: dict[str, Any] = {
        "charge_mosfet_enabled": bool(data[16] & 0x2),
        "discharge_mosfet_enabled": bool(data[16] & 0x4),
        "heater_enabled": bool(data[17] & 0x20),
    }

    # RNGPRO-family batteries do not expose the fault bitmask across the same
    # 14-byte span; the generic decode picks up non-fault status bytes (e.g.
    # 0xAA) and yields a spurious, permanently-nonzero value. Until the RNGPRO
    # fault-register layout is characterized, omit the problem code so consumers
    # represent it as unknown rather than falsely reporting no fault.
    if variant != BATTERY_VARIANT_RNGPRO:
        parsed["battery_problem_code"] = int.from_bytes(data[3:17], byteorder="big") & (
            ~0xE
        )

    return parsed
