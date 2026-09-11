"""Regression tests for legacy batteries using 0.1 V cell encoding."""

from renogy_ble.battery import (
    BATTERY_VARIANT_LEGACY,
    modbus_crc,
    parse_battery_cell_status,
)


def _battery_frame(device_id: int, payload: bytes) -> bytes:
    frame = bytearray([device_id, 0x03, len(payload)])
    frame.extend(payload)
    crc_low, crc_high = modbus_crc(frame)
    frame.extend([crc_low, crc_high])
    return bytes(frame)


def test_legacy_cell_status_infers_tenth_volt_scale() -> None:
    """Legacy BT-TH packs with raw values below 100 should decode as 0.1 V."""
    payload = bytearray(68)
    payload[0:2] = (4).to_bytes(2, "big")
    for index, value in enumerate((32, 32, 33, 33)):
        start = 2 + index * 2
        payload[start : start + 2] = value.to_bytes(2, "big")

    frame = _battery_frame(0x30, bytes(payload))
    parsed = parse_battery_cell_status(frame, variant=BATTERY_VARIANT_LEGACY)

    assert parsed["cell_voltages"] == [3.2, 3.2, 3.3, 3.3]
    assert parsed["cell_voltage_min"] == 3.2
    assert parsed["cell_voltage_max"] == 3.3
    assert parsed["cell_voltage_delta"] == 0.1
