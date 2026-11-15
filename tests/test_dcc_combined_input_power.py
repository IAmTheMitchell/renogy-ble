"""Regression tests for DCC combined-input versus solar-only power.

The two 50A G7 frames were captured from hardware in renogy-ha issue #150.
30A and solar-only cases use synthetic register values following that layout.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from renogy_ble.ble import RenogyBLEDevice, modbus_crc

ALTERNATOR_ONLY_G7 = (
    "ff0340001b0083007e1f19007c00a500140000000000140000007c009e"
    "0e700000021e000000000000000b00000027000000090000061f00000000"
    "000059d500000000c0b6"
)
SOLAR_AND_ALTERNATOR_G7 = (
    "ff03400021008402552a19007c025b004a00b00070005d0013007c009e"
    "0e700000021e00000061000005ea000000270000000b0000068000000000"
    "00005fb4000000005817"
)


def _device(model: str, device_type: str = "dcc") -> RenogyBLEDevice:
    ble_device = MagicMock()
    ble_device.name = "BT-TH-TEST"
    ble_device.address = "AA:BB:CC:DD:EE:FF"
    device = RenogyBLEDevice(ble_device, device_type=device_type)
    device.parsed_data["model"] = model
    return device


def _dynamic_frame(alternator_power: int, total_or_solar_power: int) -> bytes:
    """Replace the two power registers in a real 0x0100 response and fix CRC."""
    data = bytearray.fromhex(SOLAR_AND_ALTERNATOR_G7)
    data[15:17] = alternator_power.to_bytes(2, "big")
    data[21:23] = total_or_solar_power.to_bytes(2, "big")
    data[-2:] = bytes(modbus_crc(data[:-2]))
    return bytes(data)


@pytest.mark.parametrize(
    ("frame", "alternator", "solar", "combined"),
    [
        (ALTERNATOR_ONLY_G7, 20, 0, 20),
        (SOLAR_AND_ALTERNATOR_G7, 74, 19, 93),
    ],
)
def test_hardware_g7_frames_expose_separate_input_powers(
    frame: str, alternator: int, solar: int, combined: int
) -> None:
    """Use captured, CRC-valid frames from a physical RBC50D1S-G7 charger."""
    device = _device("RBC50D1S-G7")
    assert device.update_parsed_data(
        bytes.fromhex(frame), register=0x0100, cmd_name="dynamic_data"
    )
    assert device.parsed_data["alternator_power"] == alternator
    assert device.parsed_data["solar_power"] == solar
    assert device.parsed_data["combined_input_power"] == combined


@pytest.mark.parametrize("model", ["RBC30D1S-G4", "RBC50D1S-G7"])
@pytest.mark.parametrize(
    ("alternator", "total", "solar"),
    [(0, 30, 30), (30, 30, 0), (20, 54, 34)],
)
def test_rbc_30a_and_50a_input_modes(
    model: str, alternator: int, total: int, solar: int
) -> None:
    """Check solar-only, alternator-only and combined-input calculations."""
    device = _device(model)
    assert device.update_parsed_data(
        _dynamic_frame(alternator, total), 0x0100, "dynamic_data"
    )
    assert device.parsed_data["combined_input_power"] == total
    assert device.parsed_data["alternator_power"] == alternator
    assert device.parsed_data["solar_power"] == solar


@pytest.mark.parametrize("model", ["DCC50S", "RBC20D1U", "Dcc", ""])
def test_other_or_unknown_dcc_models_keep_existing_register_mapping(model: str) -> None:
    """Never reinterpret the shared register for models without evidence."""
    device = _device(model)
    assert device.update_parsed_data(
        bytes.fromhex(SOLAR_AND_ALTERNATOR_G7), 0x0100, "dynamic_data"
    )
    assert device.parsed_data["solar_power"] == 93
    assert device.parsed_data["alternator_power"] == 74
    assert "combined_input_power" not in device.parsed_data


def test_missing_alternator_value_does_not_publish_fake_solar_power() -> None:
    """Keep the reported total without inventing solar from a partial read."""
    device = _device("RBC50D1S-G7")
    parsed = {"solar_power": 93}
    device._normalize_dcc_input_power(parsed)
    assert parsed == {"combined_input_power": 93}


def test_rounded_total_never_produces_negative_solar() -> None:
    """One-watt Modbus rounding cannot yield physically negative solar input."""
    device = _device("RBC50D1S-G7")
    parsed = {"solar_power": 19, "alternator_power": 20}
    device._normalize_dcc_input_power(parsed)
    assert parsed == {
        "solar_power": 0,
        "alternator_power": 20,
        "combined_input_power": 19,
    }


def test_corrupt_frame_never_publishes_new_power_fields() -> None:
    """Retain existing CRC enforcement before applying power normalization."""
    device = _device("RBC50D1S-G7")
    frame = bytearray.fromhex(SOLAR_AND_ALTERNATOR_G7)
    frame[-1] ^= 0x01
    assert not device.update_parsed_data(bytes(frame), 0x0100, "dynamic_data")
    assert "solar_power" not in device.parsed_data
    assert "combined_input_power" not in device.parsed_data
