"""Tests for the Renogy RIV4835CSH1S inverter profile."""

import pytest

from renogy_ble.ble import RIV4835CSH1S_MODEL, RenogyBleClient


def test_riv4835csh1s_read_profile() -> None:
    """Use the validated short register reads and skip unsupported 4311."""
    specs = RenogyBleClient._inverter_read_specs(RIV4835CSH1S_MODEL)

    assert [(spec.register, spec.word_count, spec.parser_name) for spec in specs] == [
        (4000, 10, "_parse_inverter_main_response"),
        (4109, 1, "_parse_inverter_device_id_response"),
        (4327, 7, "_parse_riv4835csh1s_charging_response"),
        (4408, 6, "_parse_riv4835csh1s_load_response"),
    ]
    assert specs[0].retries == 2
    assert all(spec.register != 4311 for spec in specs)


def test_default_inverter_profile_is_unchanged() -> None:
    """Keep the existing generic inverter command set for other models."""
    specs = RenogyBleClient._inverter_read_specs(None)

    assert [(spec.register, spec.word_count) for spec in specs] == [
        (4000, 32),
        (4408, 6),
        (4109, 1),
        (4311, 8),
    ]


def test_riv4835csh1s_main_response() -> None:
    """Parse register 4000 from a captured RIV4835CSH1S response."""
    data = bytes.fromhex("200314046f06a4046b001e177102000227000000001771352f")

    parsed = RenogyBleClient._parse_inverter_main_response(data)

    assert parsed["ac_input_voltage"] == pytest.approx(113.5)
    assert parsed["ac_input_current"] == pytest.approx(17.0)
    assert parsed["ac_output_voltage"] == pytest.approx(113.1)
    assert parsed["ac_output_current"] == pytest.approx(0.3)
    assert parsed["ac_output_frequency"] == pytest.approx(60.01)
    assert parsed["battery_voltage"] == pytest.approx(51.2)
    assert parsed["temperature"] == pytest.approx(55.1)
    assert parsed["input_frequency"] == pytest.approx(60.01)


def test_riv4835csh1s_charging_response() -> None:
    """Parse charging, PV, and signed battery-current telemetry."""
    data = bytes.fromhex("20030e003cfe1102690069028a000209e7e8e0")

    parsed = RenogyBleClient._parse_riv4835csh1s_charging_response(data)

    assert parsed["battery_percentage"] == 60
    assert parsed["battery_current"] == pytest.approx(-49.5)
    assert parsed["pv_voltage"] == pytest.approx(61.7)
    assert parsed["pv_current"] == pytest.approx(10.5)
    assert parsed["pv_power"] == 650
    assert parsed["charging_status"] == "constant voltage"
    assert parsed["charging_power"] == 2535


def test_riv4835csh1s_discharge_current_is_positive() -> None:
    """Preserve the inverter's positive-discharge current convention."""
    data = bytes.fromhex("20030e002a004301f90000000000000000a531")

    parsed = RenogyBleClient._parse_riv4835csh1s_charging_response(data)

    assert parsed["battery_percentage"] == 42
    assert parsed["battery_current"] == pytest.approx(6.7)
    assert parsed["charging_status"] == "deactivated"
    assert parsed["charging_power"] == 0


def test_riv4835csh1s_load_response() -> None:
    """Parse load current, power, line charging current, and load percentage."""
    data = bytes.fromhex("20030c000200140016000001710000a0f6")

    parsed = RenogyBleClient._parse_riv4835csh1s_load_response(data)

    assert parsed["load_current"] == pytest.approx(0.2)
    assert parsed["load_active_power"] == 20
    assert parsed["load_apparent_power"] == 22
    assert parsed["line_charging_current"] == pytest.approx(36.9)
    assert parsed["load_percentage"] == 0
