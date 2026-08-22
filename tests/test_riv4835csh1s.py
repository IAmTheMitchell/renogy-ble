"""Tests for the Renogy RIV4835CSH1S inverter profile."""

import asyncio
from typing import Callable
from unittest.mock import MagicMock

import pytest

from renogy_ble import RIV4835CSH1S_MODEL, RenogyBleClient, RenogyBLEDevice
from renogy_ble.ble import INVERTER_DEVICE_ID, modbus_crc


def _modbus_read_response(register_values: list[int]) -> bytes:
    """Build a valid inverter response for the supplied register values."""
    payload = bytearray([INVERTER_DEVICE_ID, 0x03, len(register_values) * 2])
    for value in register_values:
        payload.extend(value.to_bytes(2, "big"))
    payload.extend(modbus_crc(payload))
    return bytes(payload)


def test_riv4835csh1s_read_profile() -> None:
    """Use the validated short register reads and skip unsupported 4311."""
    specs = RenogyBleClient._inverter_read_specs(RIV4835CSH1S_MODEL)

    assert [(spec.register, spec.word_count, spec.parser_name) for spec in specs] == [
        (4000, 10, "_parse_inverter_main_response"),
        (4109, 1, "_parse_inverter_device_id_response"),
        (4327, 7, "_parse_inverter_charging_response"),
        (4408, 6, "_parse_riv4835csh1s_load_response"),
    ]
    assert specs[0].retries == 2
    assert all(spec.register != 4311 for spec in specs)


def test_default_inverter_profile_is_unchanged() -> None:
    """Keep the existing generic inverter command set for other models."""
    specs = RenogyBleClient._inverter_read_specs(None)

    assert [(spec.register, spec.word_count) for spec in specs] == [
        (4000, 10),
        (4408, 6),
        (4327, 7),
        (4109, 1),
        (4311, 8),
        (4456, 1),
        (4422, 1),
        (4430, 1),
        (4452, 1),
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

    parsed = RenogyBleClient._parse_inverter_charging_response(data)

    assert parsed["battery_percentage"] == 60
    assert parsed["charging_current"] == pytest.approx(-49.5)
    assert parsed["solar_voltage"] == pytest.approx(61.7)
    assert parsed["solar_current"] == pytest.approx(10.5)
    assert parsed["solar_power"] == 650
    assert parsed["charging_status"] == "constant_voltage"
    assert parsed["charging_power"] == 2535


def test_riv4835csh1s_discharge_current_is_positive() -> None:
    """Preserve the inverter's positive-discharge current convention."""
    data = bytes.fromhex("20030e002a004301f90000000000000000a531")

    parsed = RenogyBleClient._parse_inverter_charging_response(data)

    assert parsed["battery_percentage"] == 42
    assert parsed["charging_current"] == pytest.approx(6.7)
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


def test_riv4835csh1s_read_uses_only_supported_registers(monkeypatch) -> None:
    """Read captured RIV frames without probing unsupported registers."""

    class DummyClient:
        def __init__(self) -> None:
            self.is_connected = True
            self.writes: list[bytes] = []
            self._notify_handler: Callable[[object | None, bytes], None] | None = None

        async def start_notify(self, *_args, **_kwargs) -> None:
            self._notify_handler = _args[1]

        async def write_gatt_char(self, _uuid, payload) -> None:
            if self._notify_handler is None:
                raise AssertionError("Notify handler was not set.")

            request = bytes(payload)
            self.writes.append(request)
            register = int.from_bytes(request[2:4], "big")
            responses = {
                4000: bytes.fromhex(
                    "200314046f06a4046b001e177102000227000000001771352f"
                ),
                4109: _modbus_read_response([32]),
                4327: bytes.fromhex("20030e003cfe1102690069028a000209e7e8e0"),
                4408: bytes.fromhex("20030c000200140016000001710000a0f6"),
            }
            self._notify_handler(None, responses[register])

        async def read_gatt_char(self, *_args, **_kwargs) -> bytes:
            return b"\x00"

        async def stop_notify(self, *_args, **_kwargs) -> None:
            return None

        async def disconnect(self) -> None:
            self.is_connected = False

    dummy_client = DummyClient()

    async def _fake_establish_connection(*_args, **_kwargs) -> DummyClient:
        return dummy_client

    from renogy_ble import ble as ble_module

    monkeypatch.setattr(ble_module, "establish_connection", _fake_establish_connection)

    ble_device = MagicMock()
    ble_device.name = "BT-TH-66E5CDEB"
    ble_device.address = "AA:BB:CC:DD:EE:FF"
    device = RenogyBLEDevice(
        ble_device,
        device_type="inverter",
        model_hint=RIV4835CSH1S_MODEL,
    )

    result = asyncio.run(RenogyBleClient().read_device(device))

    assert result.success is True
    assert result.error is None
    assert result.parsed_data["model"] == RIV4835CSH1S_MODEL
    assert result.parsed_data["device_id"] == 32
    assert result.parsed_data["charging_current"] == pytest.approx(-49.5)
    assert result.parsed_data["solar_voltage"] == pytest.approx(61.7)
    assert result.parsed_data["load_current"] == pytest.approx(0.2)
    assert [int.from_bytes(request[2:4], "big") for request in dummy_client.writes] == [
        4000,
        4109,
        4327,
        4408,
    ]
