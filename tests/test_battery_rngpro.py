"""Regression tests for RNGPRO-family batteries (e.g. RBT12500LFP-SHBT).

Frames below are raw Modbus responses captured over BLE from a real Renogy
RBT12500LFP-SHBT (12 V / 500 Ah) battery, which advertises as
``RNGPRO125BAT-*``. Ground-truth values were confirmed against the battery's
own readout: 13.3 V, ~2 A discharge, 3.3 V/cell, ~23 C, 500 Ah.
"""

import renogy_ble
from renogy_ble.battery import (
    BATTERY_VARIANT_PRO,
    BATTERY_VARIANT_RNGPRO,
    build_battery_command,
    detect_battery_variant,
    is_supported_battery_name,
    parse_battery_cell_status,
    parse_battery_mosfet_status,
    parse_battery_pack_status,
)

# Raw response frames captured from the battery (full frames incl. id/func/len/CRC).
PACK_STATUS = bytes.fromhex("ff030eff370085000746ee0007a1200018f9db")
CELL_STATUS = bytes.fromhex(
    "ff034400040021002100210021000000000000000000000000000000000000000000000000000300e900e300e200000000000000000000000000000000000000000000000000001917"
)
MOSFET_STATUS = bytes.fromhex("ff0310000000aa000000000000000000060000850f")


def test_detect_rngpro_variant() -> None:
    assert detect_battery_variant("RNGPRO125BAT-EF036881") == BATTERY_VARIANT_RNGPRO
    assert is_supported_battery_name("RNGPRO125BAT-EF036881") is True
    # existing RNGRBP/RNGC batteries must remain classified as plain "pro"
    assert detect_battery_variant("RNGRBP123456") == BATTERY_VARIANT_PRO


def test_rngpro_variant_is_exported_from_package() -> None:
    assert renogy_ble.BATTERY_VARIANT_RNGPRO == BATTERY_VARIANT_RNGPRO
    assert "BATTERY_VARIANT_RNGPRO" in renogy_ble.__all__


def test_rngpro_uses_universal_device_id() -> None:
    frame = build_battery_command(BATTERY_VARIANT_RNGPRO, 0x13B2, 0x0007)
    assert frame[:6] == bytes([0xFF, 0x03, 0x13, 0xB2, 0x00, 0x07])


def test_rngpro_pack_status_scaling() -> None:
    parsed = parse_battery_pack_status(PACK_STATUS, variant=BATTERY_VARIANT_RNGPRO)
    assert parsed["battery_voltage"] == 13.3
    # current is 0.01 A units for RNGPRO: 0xFF37 -> -201 -> -2.01 A (not -20.1)
    assert parsed["battery_current"] == -2.01
    assert parsed["battery_power"] == round(13.3 * -2.01, 3)
    assert parsed["battery_capacity"] == 500.0
    assert parsed["battery_remaining_capacity"] == 476.91
    assert parsed["battery_percentage"] == 95.4
    assert parsed["battery_cycle_count"] == 24


def test_rngpro_cell_status_scaling() -> None:
    parsed = parse_battery_cell_status(CELL_STATUS, variant=BATTERY_VARIANT_RNGPRO)
    assert parsed["cell_count"] == 4
    # cell voltages are 0.1 V units for RNGPRO: 0x0021 -> 33 -> 3.3 V (not 0.033)
    assert parsed["cell_voltages"] == [3.3, 3.3, 3.3, 3.3]
    assert parsed["battery_temperature_sensors"] == 3
    assert parsed["battery_temperature_values"] == [23.3, 22.7, 22.6]
    assert parsed["battery_temperature"] == 22.9


def test_rngpro_mosfet_status_no_false_fault() -> None:
    parsed = parse_battery_mosfet_status(MOSFET_STATUS, variant=BATTERY_VARIANT_RNGPRO)
    # The generic 14-byte fault span would yield a spurious huge value here.
    assert "battery_problem_code" not in parsed
    assert parsed["charge_mosfet_enabled"] is True
    assert parsed["discharge_mosfet_enabled"] is True
    assert parsed["heater_enabled"] is False


def test_existing_pro_mosfet_status_keeps_fault_decoder() -> None:
    parsed = parse_battery_mosfet_status(MOSFET_STATUS, variant=BATTERY_VARIANT_PRO)
    assert parsed["battery_problem_code"] > 0
