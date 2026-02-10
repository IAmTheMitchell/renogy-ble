"""Tests for Smart Shunt payload parsing."""

from renogy_ble.shunt import (
    KEY_SHUNT_CURRENT,
    KEY_SHUNT_ENERGY,
    KEY_SHUNT_POWER,
    KEY_SHUNT_SOC,
    KEY_SHUNT_VOLTAGE,
    parse_shunt_payload,
)


def _build_payload(
    voltage: float = 13.2, current: float = -5.4, starter_voltage: float = 13.1
) -> bytes:
    """Build a synthetic 110-byte Smart Shunt payload."""
    payload = bytearray(110)
    payload[25:28] = int(voltage * 1000).to_bytes(3, "big", signed=False)
    payload[21:24] = int(current * 1000).to_bytes(3, "big", signed=True)
    payload[30:32] = int(starter_voltage * 1000).to_bytes(2, "big", signed=False)
    payload[34:36] = int(85.4 * 10).to_bytes(2, "big", signed=False)
    payload[66:68] = int(24.5 * 10).to_bytes(2, "big", signed=False)
    return bytes(payload)


def test_parse_shunt_payload_returns_expected_fields() -> None:
    """Validate parsing returns expected values for a valid payload."""
    data = parse_shunt_payload(_build_payload())

    assert data is not None
    assert data[KEY_SHUNT_VOLTAGE] == 13.2
    assert data[KEY_SHUNT_CURRENT] == -5.4
    assert data[KEY_SHUNT_POWER] == round(13.2 * -5.4, 2)
    assert data[KEY_SHUNT_SOC] == 85.4
    assert data[KEY_SHUNT_ENERGY] is None
    assert data["battery_temperature"] == 24.5


def test_parse_shunt_payload_rejects_out_of_range_voltage() -> None:
    """Validate obviously invalid voltage frames are rejected."""
    data = parse_shunt_payload(_build_payload(voltage=150.0))
    assert data is None


def test_parse_shunt_payload_rejects_short_payload() -> None:
    """Validate short payloads are rejected."""
    data = parse_shunt_payload(bytes([0x00] * 12))
    assert data is None
