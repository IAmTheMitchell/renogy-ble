"""Tests for Renogy battery protocol helpers."""

from renogy_ble.battery import (
    BATTERY_VARIANT_LEGACY,
    BATTERY_VARIANT_PRO,
    build_battery_command,
    detect_battery_variant,
    is_supported_battery_name,
    parse_battery_cell_status,
    parse_battery_device_info,
    parse_battery_mosfet_status,
    parse_battery_pack_status,
)


def _battery_frame(
    device_id: int,
    payload: bytes,
) -> bytes:
    from renogy_ble.battery import modbus_crc

    frame = bytearray([device_id, 0x03, len(payload)])
    frame.extend(payload)
    crc_low, crc_high = modbus_crc(frame)
    frame.extend([crc_low, crc_high])
    return bytes(frame)


def test_detect_battery_variant_from_name_and_manufacturer_data() -> None:
    """Battery detection should distinguish Pro and legacy families."""
    assert detect_battery_variant("RNGRBP123456") == BATTERY_VARIANT_PRO
    assert detect_battery_variant("RNGC123456") == BATTERY_VARIANT_PRO
    assert detect_battery_variant("BT-TH-BATT01") == BATTERY_VARIANT_LEGACY
    assert detect_battery_variant("BT-TH-123456") is None
    assert (
        detect_battery_variant("Unknown", manufacturer_data={0xE14C: b"\x01"})
        == BATTERY_VARIANT_PRO
    )
    assert detect_battery_variant("Other") is None


def test_is_supported_battery_name_accepts_manufacturer_data() -> None:
    """The public battery helper should match the read-path detection inputs."""
    assert is_supported_battery_name("BT-BATTERY") is False
    assert (
        is_supported_battery_name("BT-BATTERY", manufacturer_data={0xE14C: b"\x01"})
        is True
    )


def test_build_battery_command_uses_variant_device_id() -> None:
    """Battery commands should use the variant-specific response header ID."""
    legacy = build_battery_command(BATTERY_VARIANT_LEGACY, 0x13B2, 0x0007)
    pro = build_battery_command(BATTERY_VARIANT_PRO, 0x13B2, 0x0007)

    assert legacy[:6] == bytes([0x30, 0x03, 0x13, 0xB2, 0x00, 0x07])
    assert pro[:6] == bytes([0xFF, 0x03, 0x13, 0xB2, 0x00, 0x07])


def test_parse_battery_device_info() -> None:
    """Battery device info should expose serial, name, and software version."""
    payload = bytearray(56)
    payload[12:28] = b"SERIAL-RENOGY-01"
    payload[36:52] = b"House Battery 1 "
    payload[52:56] = b"1.02"
    frame = _battery_frame(0x30, bytes(payload))

    parsed = parse_battery_device_info(frame, variant=BATTERY_VARIANT_LEGACY)

    assert parsed["battery_variant"] == BATTERY_VARIANT_LEGACY
    assert parsed["serial_number"] == "SERIAL-RENOGY-01"
    assert parsed["device_name"] == "House Battery 1"
    assert parsed["sw_version"] == "1.02"


def test_parse_battery_pack_status_variants() -> None:
    """Legacy and Pro batteries should use their respective current scaling."""
    payload = bytearray(14)
    payload[0:2] = int(1234).to_bytes(2, "big", signed=True)
    payload[2:4] = (512).to_bytes(2, "big")
    payload[4:8] = (50000).to_bytes(4, "big")
    payload[8:12] = (100000).to_bytes(4, "big")
    payload[12:14] = (42).to_bytes(2, "big")

    legacy_frame = _battery_frame(0x30, bytes(payload))
    pro_frame = _battery_frame(0xFF, bytes(payload))

    legacy = parse_battery_pack_status(legacy_frame, variant=BATTERY_VARIANT_LEGACY)
    pro = parse_battery_pack_status(pro_frame, variant=BATTERY_VARIANT_PRO)

    assert legacy["battery_voltage"] == 51.2
    assert legacy["battery_current"] == 12.34
    assert legacy["battery_percentage"] == 50.0
    assert legacy["battery_cycle_count"] == 42
    assert pro["battery_current"] == 123.4


def test_parse_battery_pack_status_preserves_fractional_capacity() -> None:
    """Battery pack status should preserve fractional amp-hour capacities."""
    payload = bytearray(14)
    payload[0:2] = int(250).to_bytes(2, "big", signed=True)
    payload[2:4] = (512).to_bytes(2, "big")
    payload[4:8] = (50000).to_bytes(4, "big")
    payload[8:12] = (99500).to_bytes(4, "big")
    payload[12:14] = (42).to_bytes(2, "big")

    frame = _battery_frame(0x30, bytes(payload))

    parsed = parse_battery_pack_status(frame, variant=BATTERY_VARIANT_LEGACY)

    assert parsed["battery_remaining_capacity"] == 50.0
    assert parsed["battery_capacity"] == 99.5
    assert parsed["battery_percentage"] == 50.3


def test_parse_battery_cell_status_and_faults() -> None:
    """Cell and fault parsing should expose derived metrics."""
    payload = bytearray(68)
    payload[0:2] = (4).to_bytes(2, "big")
    for index, value in enumerate((3300, 3290, 3310, 3320)):
        start = 2 + index * 2
        payload[start : start + 2] = value.to_bytes(2, "big")
    payload[34:36] = (2).to_bytes(2, "big")
    payload[36:38] = (215).to_bytes(2, "big", signed=True)
    payload[38:40] = (225).to_bytes(2, "big", signed=True)

    cell_frame = _battery_frame(0x30, bytes(payload))
    parsed_cells = parse_battery_cell_status(cell_frame, variant=BATTERY_VARIANT_LEGACY)

    assert parsed_cells["cell_count"] == 4
    assert parsed_cells["cell_voltages"] == [3.3, 3.29, 3.31, 3.32]
    assert parsed_cells["cell_voltage_min"] == 3.29
    assert parsed_cells["cell_voltage_max"] == 3.32
    assert parsed_cells["cell_voltage_delta"] == 0.03
    assert parsed_cells["battery_temperature"] == 22.0

    fault_payload = bytearray(16)
    fault_payload[13] = 0x16
    fault_payload[14] = 0x20
    fault_frame = _battery_frame(0x30, bytes(fault_payload))
    parsed_faults = parse_battery_mosfet_status(
        fault_frame, variant=BATTERY_VARIANT_LEGACY
    )

    assert parsed_faults["battery_problem_code"] > 0
    assert parsed_faults["charge_mosfet_enabled"] is True
    assert parsed_faults["discharge_mosfet_enabled"] is True
    assert parsed_faults["heater_enabled"] is True
