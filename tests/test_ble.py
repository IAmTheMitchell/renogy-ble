"""Tests for BLE helpers and device tracking."""

import asyncio
import builtins
from datetime import datetime, timedelta
from typing import Callable
from unittest.mock import MagicMock

import pytest

from renogy_ble.battery import BATTERY_VARIANT_LEGACY, BATTERY_VARIANT_PRO
from renogy_ble.ble import (
    DEFAULT_DEVICE_ID,
    INVERTER_DEVICE_ID,
    RENOGY_READ_CHAR_UUID,
    RENOGY_WRITE_CHAR_UUID,
    UNAVAILABLE_RETRY_INTERVAL,
    BleakError,
    RenogyBleClient,
    RenogyBLEDevice,
    RenogyBleReadResult,
    clean_device_name,
    create_modbus_read_request,
    create_modbus_write_request,
    modbus_crc,
)


def _mock_ble_device(name="BT-TH-TEST", address="AA:BB:CC:DD:EE:FF"):
    device = MagicMock()
    device.name = name
    device.address = address
    device.rssi = -60
    return device


def _modbus_read_response(device_id: int, register_values: list[int]) -> bytes:
    payload = bytearray([device_id, 0x03, len(register_values) * 2])
    for value in register_values:
        payload.extend(value.to_bytes(2, "big"))
    crc_low, crc_high = modbus_crc(payload)
    payload.extend([crc_low, crc_high])
    return bytes(payload)


def _modbus_ascii_response(device_id: int, value: str, register_count: int) -> bytes:
    encoded = value.encode("ascii")
    payload_bytes = encoded.ljust(register_count * 2, b"\x00")
    payload = bytearray([device_id, 0x03, len(payload_bytes)])
    payload.extend(payload_bytes)
    crc_low, crc_high = modbus_crc(payload)
    payload.extend([crc_low, crc_high])
    return bytes(payload)


def test_modbus_crc_known_vector():
    payload = bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x01])
    crc_low, crc_high = modbus_crc(payload)
    assert (crc_low, crc_high) == (0x84, 0x0A)


def test_create_modbus_read_request_appends_crc():
    frame = create_modbus_read_request(DEFAULT_DEVICE_ID, 3, 0x0010, 2)
    assert frame[:6] == bytes([DEFAULT_DEVICE_ID, 3, 0x00, 0x10, 0x00, 0x02])
    crc_low, crc_high = modbus_crc(frame[:6])
    assert frame[6:] == bytes([crc_low, crc_high])


def test_create_modbus_write_request_appends_crc():
    frame = create_modbus_write_request(
        DEFAULT_DEVICE_ID, 0x010A, 0x0001, function_code=6
    )
    assert frame[:6] == bytes([DEFAULT_DEVICE_ID, 6, 0x01, 0x0A, 0x00, 0x01])
    crc_low, crc_high = modbus_crc(frame[:6])
    assert frame[6:] == bytes([crc_low, crc_high])


def test_create_modbus_write_request_defaults_function_code():
    frame = create_modbus_write_request(DEFAULT_DEVICE_ID, 0x010A, 0x0001)
    assert frame[:6] == bytes([DEFAULT_DEVICE_ID, 0x06, 0x01, 0x0A, 0x00, 0x01])
    crc_low, crc_high = modbus_crc(frame[:6])
    assert frame[6:] == bytes([crc_low, crc_high])


def test_device_uses_explicit_advertisement_name_for_battery_family() -> None:
    """The advertisement local name should override a generic BLE OS name."""
    device = RenogyBLEDevice(
        _mock_ble_device(name="Generic OS name"),
        device_type="battery",
        manufacturer_data={0xE14C: b"\x01"},
        advertisement_name="RNGRBP123456",
    )

    assert device.name == "Generic OS name"
    assert device.advertised_name == "RNGRBP123456"
    assert device.battery_variant == BATTERY_VARIANT_PRO


def test_extract_valid_read_response_skips_junk_prefix():
    client = RenogyBleClient()
    payload = bytes([DEFAULT_DEVICE_ID, 0x03, 0x02, 0x12, 0x34])
    crc_low, crc_high = modbus_crc(payload)
    valid_frame = payload + bytes([crc_low, crc_high])

    response = client._extract_valid_read_response(
        b"\x99\x88" + valid_frame,
        function_code=0x03,
        word_count=1,
    )

    assert response == valid_frame


def test_extract_valid_read_response_rejects_invalid_crc():
    client = RenogyBleClient()
    invalid_frame = bytes([DEFAULT_DEVICE_ID, 0x03, 0x02, 0x12, 0x34, 0x00, 0x00])

    response = client._extract_valid_read_response(
        invalid_frame,
        function_code=0x03,
        word_count=1,
    )

    assert response is None


def test_extract_valid_read_response_prefers_latest_matching_frame():
    client = RenogyBleClient()
    stale_payload = bytes([DEFAULT_DEVICE_ID, 0x03, 0x02, 0x12, 0x34])
    stale_crc_low, stale_crc_high = modbus_crc(stale_payload)
    stale_frame = stale_payload + bytes([stale_crc_low, stale_crc_high])

    latest_payload = bytes([DEFAULT_DEVICE_ID, 0x03, 0x02, 0x56, 0x78])
    latest_crc_low, latest_crc_high = modbus_crc(latest_payload)
    latest_frame = latest_payload + bytes([latest_crc_low, latest_crc_high])

    response = client._extract_valid_read_response(
        b"\x99\x88" + stale_frame + latest_frame,
        function_code=0x03,
        word_count=1,
    )

    assert response == latest_frame


def test_clean_device_name_strips_whitespace():
    assert clean_device_name("  Renogy  BLE\t") == "Renogy BLE"
    assert clean_device_name("") == ""


def test_device_availability_tracking():
    device = RenogyBLEDevice(_mock_ble_device())

    device.update_availability(False)
    device.update_availability(False)
    device.update_availability(False)
    assert device.is_available is False

    device.update_availability(True)
    assert device.is_available is True
    assert device.failure_count == 0


def test_should_retry_connection_interval():
    device = RenogyBLEDevice(_mock_ble_device())
    device.available = False
    device.failure_count = device.max_failures
    device.last_unavailable_time = None

    assert device.should_retry_connection is False
    assert device.last_unavailable_time is not None

    device.last_unavailable_time = datetime.now() - timedelta(
        minutes=UNAVAILABLE_RETRY_INTERVAL + 1
    )
    assert device.should_retry_connection is True


def test_read_device_skips_disconnect_when_not_connected(monkeypatch):
    class DummyClient:
        def __init__(self):
            self.is_connected = False
            self.disconnect_called = False
            self._notify_handler: Callable[[object | None, bytes], None] | None = None

        async def start_notify(self, *_args, **_kwargs):
            self._notify_handler = _args[1]

        async def write_gatt_char(self, *_args, **_kwargs):
            # Provide enough bytes to satisfy expected length (7 bytes).
            if self._notify_handler is None:
                raise AssertionError("Notify handler was not set.")
            payload = bytes([DEFAULT_DEVICE_ID, 0x03, 0x02, 0x00, 0x00])
            crc_low, crc_high = modbus_crc(payload)
            self._notify_handler(None, payload + bytes([crc_low, crc_high]))

        async def stop_notify(self, *_args, **_kwargs):
            return None

        async def disconnect(self):
            self.disconnect_called = True
            raise BleakError("disconnect called unexpectedly")

    dummy_client = DummyClient()

    async def _fake_establish_connection(*_args, **_kwargs):
        return dummy_client

    from renogy_ble import ble as ble_module

    monkeypatch.setattr(ble_module, "establish_connection", _fake_establish_connection)

    client = RenogyBleClient(commands={"test_device": {"status": (3, 0x0000, 1)}})
    device = RenogyBLEDevice(_mock_ble_device(), device_type="test_device")

    def _update_parsed_data(
        _raw_data: bytes, register: int, cmd_name: str = "unknown"
    ) -> bool:
        _ = register, cmd_name
        return True

    monkeypatch.setattr(device, "update_parsed_data", _update_parsed_data)

    result = asyncio.run(client.read_device(device))

    assert result.success is True
    assert result.error is None
    assert dummy_client.disconnect_called is False


def test_read_device_delegates_shunt300_to_shunt_client(monkeypatch):
    init_kwargs: dict[str, object] = {}

    class DummyShuntClient:
        def __init__(self, **kwargs):
            init_kwargs.update(kwargs)

        async def read_device(self, device):
            device.parsed_data = {"shunt_voltage": 13.2}
            return MagicMock(success=True, parsed_data=device.parsed_data, error=None)

    from renogy_ble import shunt as shunt_module

    monkeypatch.setattr(shunt_module, "ShuntBleClient", DummyShuntClient)

    client = RenogyBleClient(max_notification_wait_time=1.25, max_attempts=2)
    device = RenogyBLEDevice(_mock_ble_device(), device_type="shunt300")

    result = asyncio.run(client.read_device(device))

    assert result.success is True
    assert result.error is None
    assert result.parsed_data == {"shunt_voltage": 13.2}
    assert init_kwargs == {"max_notification_wait_time": 1.25, "max_attempts": 2}


def test_read_device_shunt300_reports_error_when_shunt_module_missing(monkeypatch):
    original_import = builtins.__import__

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "renogy_ble.shunt":
            raise ImportError("module not found")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    client = RenogyBleClient()
    device = RenogyBLEDevice(_mock_ble_device(), device_type="shunt300")

    result = asyncio.run(client.read_device(device))

    assert result.success is False
    assert isinstance(result.error, ImportError)


def test_read_device_reads_inverter_data_with_validated_frames(monkeypatch):
    class DummyClient:
        def __init__(self):
            self.is_connected = True
            self.disconnect_calls = 0
            self.stop_notify_calls = 0
            self.writes: list[bytes] = []
            self._notify_handler: Callable[[object | None, bytes], None] | None = None

        async def start_notify(self, *_args, **_kwargs):
            self._notify_handler = _args[1]

        async def write_gatt_char(self, _uuid, payload, response=None):
            if self._notify_handler is None:
                raise AssertionError("Notify handler was not set.")

            request = bytes(payload)
            self.writes.append(request)
            register = int.from_bytes(request[2:4], "big")
            responses = {
                4000: _modbus_read_response(
                    INVERTER_DEVICE_ID,
                    [2300, 125, 2295, 250, 6000, 401, 255, 0, 0, 5995],
                ),
                4408: _modbus_read_response(
                    INVERTER_DEVICE_ID, [175, 500, 550, 0, 0, 0]
                ),
                4327: _modbus_read_response(
                    INVERTER_DEVICE_ID, [80, 65526, 1200, 30, 360, 1, 360]
                ),
                4109: _modbus_read_response(INVERTER_DEVICE_ID, [32]),
                4311: _modbus_ascii_response(INVERTER_DEVICE_ID, "RIV1220PU-126", 8),
                4456: _modbus_read_response(INVERTER_DEVICE_ID, [200]),
                4422: _modbus_read_response(INVERTER_DEVICE_ID, [1500]),
                4430: _modbus_read_response(INVERTER_DEVICE_ID, [120]),
                4452: _modbus_read_response(INVERTER_DEVICE_ID, [158]),
            }
            response = responses[register]
            wrong_device = response.replace(
                bytes([INVERTER_DEVICE_ID]),
                bytes([DEFAULT_DEVICE_ID]),
                1,
            )
            self._notify_handler(None, wrong_device + response)

        async def read_gatt_char(self, *_args, **_kwargs):
            return b"\x00"

        async def stop_notify(self, *_args, **_kwargs):
            self.stop_notify_calls += 1

        async def disconnect(self):
            self.disconnect_calls += 1
            self.is_connected = False

    dummy_client = DummyClient()

    async def _fake_establish_connection(*_args, **_kwargs):
        return dummy_client

    from renogy_ble import ble as ble_module

    monkeypatch.setattr(ble_module, "establish_connection", _fake_establish_connection)

    client = RenogyBleClient()
    device = RenogyBLEDevice(
        _mock_ble_device(name="RNGRIU123456"), device_type="inverter"
    )

    result = asyncio.run(client.read_device(device))

    assert result.success is True
    assert result.error is None
    assert result.parsed_data == {
        "ac_input_voltage": 230.0,
        "ac_input_current": 1.25,
        "ac_output_voltage": 229.5,
        "ac_output_current": 2.5,
        "ac_output_frequency": 60.0,
        "battery_voltage": 40.1,
        "temperature": 25.5,
        "input_frequency": 59.95,
        "load_current": 1.75,
        "load_active_power": 500,
        "load_apparent_power": 550,
        "battery_percentage": 80,
        "charging_current": pytest.approx(-1.0),
        "solar_voltage": pytest.approx(120.0),
        "solar_current": pytest.approx(3.0),
        "solar_power": 360,
        "charging_status": "constant_current",
        "charging_power": 360,
        "device_id": 32,
        "model": "RIV1220PU-126",
        "inverter_ac_input_current_limit": pytest.approx(20.0),
        "inverter_charge_current": pytest.approx(150.0),
        "inverter_low_voltage_warn": pytest.approx(12.0),
        "inverter_over_voltage": pytest.approx(15.8),
    }
    assert [request[0] for request in dummy_client.writes] == [INVERTER_DEVICE_ID] * 9
    assert [int.from_bytes(request[2:4], "big") for request in dummy_client.writes] == [
        4000,
        4408,
        4327,
        4109,
        4311,
        4456,
        4422,
        4430,
        4452,
    ]
    assert dummy_client.stop_notify_calls == 1
    assert dummy_client.disconnect_calls == 1


def test_parse_inverter_charging_response():
    payload = _modbus_read_response(
        INVERTER_DEVICE_ID, [80, 65526, 1200, 30, 360, 1, 360]
    )
    parsed = RenogyBleClient._parse_inverter_charging_response(payload)
    assert parsed["battery_percentage"] == 80
    assert parsed["charging_current"] == pytest.approx(-1.0)  # 65526 = -10 signed, x0.1
    assert parsed["solar_voltage"] == pytest.approx(120.0)
    assert parsed["solar_current"] == pytest.approx(3.0)
    assert parsed["solar_power"] == 360
    assert parsed["charging_status"] == "constant_current"
    assert parsed["charging_power"] == 360


def test_parse_inverter_charging_response_too_short():
    assert RenogyBleClient._parse_inverter_charging_response(b"\x20\x03\x02") == {}


def test_parse_inverter_ac_input_current_limit():
    payload = _modbus_read_response(INVERTER_DEVICE_ID, [200])
    parsed = RenogyBleClient._parse_inverter_ac_input_current_limit(payload)
    assert parsed == {"inverter_ac_input_current_limit": pytest.approx(20.0)}


def test_parse_inverter_charge_current():
    payload = _modbus_read_response(INVERTER_DEVICE_ID, [1500])
    parsed = RenogyBleClient._parse_inverter_charge_current(payload)
    assert parsed == {"inverter_charge_current": pytest.approx(150.0)}


def test_parse_inverter_low_voltage_warn():
    payload = _modbus_read_response(INVERTER_DEVICE_ID, [120])
    parsed = RenogyBleClient._parse_inverter_low_voltage_warn(payload)
    assert parsed == {"inverter_low_voltage_warn": pytest.approx(12.0)}


def test_parse_inverter_over_voltage():
    payload = _modbus_read_response(INVERTER_DEVICE_ID, [158])
    parsed = RenogyBleClient._parse_inverter_over_voltage(payload)
    assert parsed == {"inverter_over_voltage": pytest.approx(15.8)}


def test_parse_inverter_setpoint_too_short():
    assert RenogyBleClient._parse_inverter_ac_input_current_limit(b"\x20\x03\x02") == {}


def test_read_device_reads_legacy_battery_data(monkeypatch):
    class DummyClient:
        def __init__(self):
            self.is_connected = True
            self.disconnect_calls = 0
            self.stop_notify_calls = 0
            self.writes: list[bytes] = []
            self._notify_handler: Callable[[object | None, bytes], None] | None = None

        async def start_notify(self, *_args, **_kwargs):
            self._notify_handler = _args[1]

        async def write_gatt_char(self, _uuid, payload, response=None):
            if self._notify_handler is None:
                raise AssertionError("Notify handler was not set.")

            request = bytes(payload)
            self.writes.append(request)
            register = int.from_bytes(request[2:4], "big")

            def _frame(device_id: int, payload_bytes: bytes) -> bytes:
                frame = bytearray([device_id, 0x03, len(payload_bytes)])
                frame.extend(payload_bytes)
                crc_low, crc_high = modbus_crc(frame)
                frame.extend([crc_low, crc_high])
                return bytes(frame)

            info_payload = bytearray(56)
            info_payload[12:28] = b"RENOGY-BAT-0001 "
            info_payload[36:52] = b"House Battery 1 "
            info_payload[52:56] = b"1.02"

            pack_payload = bytearray(14)
            pack_payload[0:2] = int(1234).to_bytes(2, "big", signed=True)
            pack_payload[2:4] = (512).to_bytes(2, "big")
            pack_payload[4:8] = (50000).to_bytes(4, "big")
            pack_payload[8:12] = (100000).to_bytes(4, "big")
            pack_payload[12:14] = (42).to_bytes(2, "big")

            cell_payload = bytearray(68)
            cell_payload[0:2] = (4).to_bytes(2, "big")
            for index, value in enumerate((330, 329, 331, 332)):
                start = 2 + index * 2
                cell_payload[start : start + 2] = value.to_bytes(2, "big")
            cell_payload[34:36] = (2).to_bytes(2, "big")
            cell_payload[36:38] = (215).to_bytes(2, "big", signed=True)
            cell_payload[38:40] = (225).to_bytes(2, "big", signed=True)

            mosfet_payload = bytearray(16)
            mosfet_payload[13] = 0x16
            mosfet_payload[14] = 0x20

            responses = {
                0x13F0: _frame(0x30, bytes(info_payload)),
                0x13B2: _frame(0x30, bytes(pack_payload)),
                0x1388: _frame(0x30, bytes(cell_payload)),
                0x13EC: _frame(0x30, bytes(mosfet_payload)),
            }
            self._notify_handler(None, responses[register])

        async def stop_notify(self, *_args, **_kwargs):
            self.stop_notify_calls += 1

        async def disconnect(self):
            self.disconnect_calls += 1
            self.is_connected = False

    dummy_client = DummyClient()

    async def _fake_establish_connection(*_args, **_kwargs):
        return dummy_client

    from renogy_ble import ble as ble_module

    monkeypatch.setattr(ble_module, "establish_connection", _fake_establish_connection)

    client = RenogyBleClient()
    device = RenogyBLEDevice(
        _mock_ble_device(name="BT-TH-BATT01"), device_type="battery"
    )

    result = asyncio.run(client.read_device(device))

    assert result.success is True
    assert result.error is None
    assert result.parsed_data["battery_variant"] == BATTERY_VARIANT_LEGACY
    assert result.parsed_data["battery_voltage"] == 51.2
    assert result.parsed_data["battery_current"] == 12.34
    assert result.parsed_data["battery_percentage"] == 50.0
    assert result.parsed_data["battery_cycle_count"] == 42
    assert result.parsed_data["cell_count"] == 4
    assert result.parsed_data["battery_temperature"] == 22.0
    assert result.parsed_data["charge_mosfet_enabled"] is True
    assert result.parsed_data["discharge_mosfet_enabled"] is True
    assert result.parsed_data["heater_enabled"] is True
    assert device.name == "House Battery 1"
    assert [request[0] for request in dummy_client.writes] == [0x30] * 4
    assert dummy_client.stop_notify_calls == 1
    assert dummy_client.disconnect_calls == 1


def test_read_device_reads_battery_pro_data(monkeypatch):
    class DummyClient:
        def __init__(self):
            self.is_connected = True
            self.disconnect_calls = 0
            self.stop_notify_calls = 0
            self.writes: list[bytes] = []
            self._notify_handler: Callable[[object | None, bytes], None] | None = None

        async def start_notify(self, *_args, **_kwargs):
            self._notify_handler = _args[1]

        async def write_gatt_char(self, _uuid, payload, response=None):
            if self._notify_handler is None:
                raise AssertionError("Notify handler was not set.")

            request = bytes(payload)
            self.writes.append(request)
            register = int.from_bytes(request[2:4], "big")

            def _frame(device_id: int, payload_bytes: bytes) -> bytes:
                frame = bytearray([device_id, 0x03, len(payload_bytes)])
                frame.extend(payload_bytes)
                crc_low, crc_high = modbus_crc(frame)
                frame.extend([crc_low, crc_high])
                return bytes(frame)

            info_payload = bytearray(56)
            info_payload[12:28] = b"RENOGY-PRO-0002 "
            info_payload[36:52] = b"Pro Battery     "
            info_payload[52:56] = b"2.10"

            pack_payload = bytearray(14)
            pack_payload[0:2] = int(1234).to_bytes(2, "big", signed=True)
            pack_payload[2:4] = (512).to_bytes(2, "big")
            pack_payload[4:8] = (65000).to_bytes(4, "big")
            pack_payload[8:12] = (100000).to_bytes(4, "big")
            pack_payload[12:14] = (7).to_bytes(2, "big")

            cell_payload = bytearray(68)
            cell_payload[0:2] = (4).to_bytes(2, "big")
            for index, value in enumerate((33, 33, 33, 33)):
                start = 2 + index * 2
                cell_payload[start : start + 2] = value.to_bytes(2, "big")
            cell_payload[34:36] = (1).to_bytes(2, "big")
            cell_payload[36:38] = (230).to_bytes(2, "big", signed=True)

            mosfet_payload = bytearray(16)
            mosfet_payload[13] = 0x02

            responses = {
                0x13F0: _frame(0xFF, bytes(info_payload)),
                0x13B2: _frame(0xFF, bytes(pack_payload)),
                0x1388: _frame(0xFF, bytes(cell_payload)),
                0x13EC: _frame(0xFF, bytes(mosfet_payload)),
            }
            self._notify_handler(None, responses[register])

        async def stop_notify(self, *_args, **_kwargs):
            self.stop_notify_calls += 1

        async def disconnect(self):
            self.disconnect_calls += 1
            self.is_connected = False

    dummy_client = DummyClient()

    async def _fake_establish_connection(*_args, **_kwargs):
        return dummy_client

    from renogy_ble import ble as ble_module

    monkeypatch.setattr(ble_module, "establish_connection", _fake_establish_connection)

    client = RenogyBleClient()
    device = RenogyBLEDevice(
        _mock_ble_device(name="RNGRBP123456"), device_type="battery"
    )

    result = asyncio.run(client.read_device(device))

    assert result.success is True
    assert result.parsed_data["battery_variant"] == BATTERY_VARIANT_PRO
    assert result.parsed_data["battery_current"] == 123.4
    assert result.parsed_data["battery_percentage"] == 65.0
    assert result.parsed_data["battery_cycle_count"] == 7
    assert result.parsed_data["cell_voltages"] == [3.3, 3.3, 3.3, 3.3]
    assert result.parsed_data["battery_temperature"] == 23.0
    assert [request[0] for request in dummy_client.writes] == [0xFF] * 4


def test_read_device_writes_battery_without_response(monkeypatch):
    """Battery ffd1 only accepts Write-Without-Response; a with-response write is
    rejected by the pack with ATT 0x0E. Every battery command must pass
    response=False (regression guard for the RNGRBP "Unlikely Error" bug)."""

    class DummyClient:
        def __init__(self):
            self.is_connected = True
            self.responses: list[object] = []
            self._notify_handler: Callable[[object | None, bytes], None] | None = None

        async def start_notify(self, *_args, **_kwargs):
            self._notify_handler = _args[1]

        async def write_gatt_char(self, _target, payload, response=None):
            if self._notify_handler is None:
                raise AssertionError("Notify handler was not set.")
            self.responses.append(response)
            request = bytes(payload)
            register = int.from_bytes(request[2:4], "big")
            # Minimal valid frames so the read loop completes for every command.
            sizes = {0x13F0: 56, 0x13B2: 14, 0x1388: 68, 0x13EC: 16}
            body = bytearray([0xFF, 0x03, sizes[register]]) + bytearray(sizes[register])
            crc_low, crc_high = modbus_crc(body)
            body.extend([crc_low, crc_high])
            self._notify_handler(None, bytes(body))

        async def stop_notify(self, *_args, **_kwargs):
            pass

        async def disconnect(self):
            self.is_connected = False

    dummy_client = DummyClient()

    async def _fake_establish_connection(*_args, **_kwargs):
        return dummy_client

    from renogy_ble import ble as ble_module

    monkeypatch.setattr(ble_module, "establish_connection", _fake_establish_connection)

    client = RenogyBleClient()
    device = RenogyBLEDevice(
        _mock_ble_device(name="RNGRBP123456"), device_type="battery"
    )

    asyncio.run(client.read_device(device))

    assert dummy_client.responses, "no battery writes were issued"
    assert all(response is False for response in dummy_client.responses)


def test_read_device_detects_battery_variant_from_manufacturer_data(monkeypatch):
    class DummyClient:
        def __init__(self):
            self.is_connected = True
            self.disconnect_calls = 0
            self.stop_notify_calls = 0
            self.writes: list[bytes] = []
            self._notify_handler: Callable[[object | None, bytes], None] | None = None

        async def start_notify(self, *_args, **_kwargs):
            self._notify_handler = _args[1]

        async def write_gatt_char(self, _uuid, payload, response=None):
            if self._notify_handler is None:
                raise AssertionError("Notify handler was not set.")

            request = bytes(payload)
            self.writes.append(request)
            register = int.from_bytes(request[2:4], "big")

            def _frame(device_id: int, payload_bytes: bytes) -> bytes:
                frame = bytearray([device_id, 0x03, len(payload_bytes)])
                frame.extend(payload_bytes)
                crc_low, crc_high = modbus_crc(frame)
                frame.extend([crc_low, crc_high])
                return bytes(frame)

            info_payload = bytearray(56)
            info_payload[12:28] = b"RENOGY-PRO-0002 "
            info_payload[36:52] = b"Pro Battery     "
            info_payload[52:56] = b"2.10"

            pack_payload = bytearray(14)
            pack_payload[0:2] = int(1234).to_bytes(2, "big", signed=True)
            pack_payload[2:4] = (512).to_bytes(2, "big")
            pack_payload[4:8] = (65000).to_bytes(4, "big")
            pack_payload[8:12] = (100000).to_bytes(4, "big")
            pack_payload[12:14] = (7).to_bytes(2, "big")

            cell_payload = bytearray(68)
            cell_payload[0:2] = (4).to_bytes(2, "big")
            for index, value in enumerate((3300, 3300, 3310, 3310)):
                start = 2 + index * 2
                cell_payload[start : start + 2] = value.to_bytes(2, "big")
            cell_payload[34:36] = (1).to_bytes(2, "big")
            cell_payload[36:38] = (230).to_bytes(2, "big", signed=True)

            mosfet_payload = bytearray(16)
            mosfet_payload[13] = 0x02

            responses = {
                0x13F0: _frame(0xFF, bytes(info_payload)),
                0x13B2: _frame(0xFF, bytes(pack_payload)),
                0x1388: _frame(0xFF, bytes(cell_payload)),
                0x13EC: _frame(0xFF, bytes(mosfet_payload)),
            }
            self._notify_handler(None, responses[register])

        async def stop_notify(self, *_args, **_kwargs):
            self.stop_notify_calls += 1

        async def disconnect(self):
            self.disconnect_calls += 1
            self.is_connected = False

    dummy_client = DummyClient()

    async def _fake_establish_connection(*_args, **_kwargs):
        return dummy_client

    from renogy_ble import ble as ble_module

    monkeypatch.setattr(ble_module, "establish_connection", _fake_establish_connection)

    client = RenogyBleClient()
    device = RenogyBLEDevice(
        _mock_ble_device(name="BT-BATTERY"),
        device_type="battery",
        manufacturer_data={0xE14C: b"\x01"},
    )

    result = asyncio.run(client.read_device(device))

    assert result.success is True
    assert result.parsed_data["battery_variant"] == BATTERY_VARIANT_PRO
    assert result.parsed_data["cell_voltages"] == [3.3, 3.3, 3.31, 3.31]
    assert [request[0] for request in dummy_client.writes] == [0xFF] * 4


def test_read_device_falls_back_to_legacy_variant_for_manual_bt_th_battery(
    monkeypatch,
):
    class DummyClient:
        def __init__(self):
            self.is_connected = True
            self.disconnect_calls = 0
            self.stop_notify_calls = 0
            self.writes: list[bytes] = []
            self._notify_handler: Callable[[object | None, bytes], None] | None = None

        async def start_notify(self, *_args, **_kwargs):
            self._notify_handler = _args[1]

        async def write_gatt_char(self, _uuid, payload, response=None):
            if self._notify_handler is None:
                raise AssertionError("Notify handler was not set.")

            request = bytes(payload)
            self.writes.append(request)
            register = int.from_bytes(request[2:4], "big")

            def _frame(device_id: int, payload_bytes: bytes) -> bytes:
                frame = bytearray([device_id, 0x03, len(payload_bytes)])
                frame.extend(payload_bytes)
                crc_low, crc_high = modbus_crc(frame)
                frame.extend([crc_low, crc_high])
                return bytes(frame)

            info_payload = bytearray(56)
            info_payload[12:28] = b"RENOGY-BAT-0001 "
            info_payload[36:52] = b"House Battery 1 "
            info_payload[52:56] = b"1.02"

            pack_payload = bytearray(14)
            pack_payload[0:2] = int(1234).to_bytes(2, "big", signed=True)
            pack_payload[2:4] = (512).to_bytes(2, "big")
            pack_payload[4:8] = (50000).to_bytes(4, "big")
            pack_payload[8:12] = (100000).to_bytes(4, "big")
            pack_payload[12:14] = (42).to_bytes(2, "big")

            cell_payload = bytearray(68)
            cell_payload[0:2] = (4).to_bytes(2, "big")
            for index, value in enumerate((330, 329, 331, 332)):
                start = 2 + index * 2
                cell_payload[start : start + 2] = value.to_bytes(2, "big")
            cell_payload[34:36] = (2).to_bytes(2, "big")
            cell_payload[36:38] = (215).to_bytes(2, "big", signed=True)
            cell_payload[38:40] = (225).to_bytes(2, "big", signed=True)

            mosfet_payload = bytearray(16)
            mosfet_payload[13] = 0x16
            mosfet_payload[14] = 0x20

            responses = {
                0x13F0: _frame(0x30, bytes(info_payload)),
                0x13B2: _frame(0x30, bytes(pack_payload)),
                0x1388: _frame(0x30, bytes(cell_payload)),
                0x13EC: _frame(0x30, bytes(mosfet_payload)),
            }
            self._notify_handler(None, responses[register])

        async def stop_notify(self, *_args, **_kwargs):
            self.stop_notify_calls += 1

        async def disconnect(self):
            self.disconnect_calls += 1
            self.is_connected = False

    dummy_client = DummyClient()

    async def _fake_establish_connection(*_args, **_kwargs):
        return dummy_client

    from renogy_ble import ble as ble_module

    monkeypatch.setattr(ble_module, "establish_connection", _fake_establish_connection)

    client = RenogyBleClient()
    device = RenogyBLEDevice(
        _mock_ble_device(name="BT-TH-123456"), device_type="battery"
    )

    result = asyncio.run(client.read_device(device))

    assert result.success is True
    assert result.parsed_data["battery_variant"] == BATTERY_VARIANT_LEGACY
    assert result.parsed_data["battery_voltage"] == 51.2
    assert [request[0] for request in dummy_client.writes] == [0x30] * 4


@pytest.mark.parametrize(
    ("write_properties", "expected_response"),
    [
        (["write-without-response"], False),
        (["write", "write-without-response"], False),
        (["write"], True),
    ],
)
def test_read_device_uses_resolved_handles_for_battery_pro_characteristics(
    monkeypatch,
    write_properties: list[str],
    expected_response: bool,
):
    class DummyCharacteristic:
        def __init__(self, uuid: str, handle: int, properties: list[str]):
            self.uuid = uuid
            self.handle = handle
            self.properties = properties

    class DummyService:
        def __init__(self, uuid: str, characteristics: list[DummyCharacteristic]):
            self.uuid = uuid
            self.characteristics = characteristics

    class DummyClient:
        def __init__(self):
            self.is_connected = True
            self.disconnect_calls = 0
            self.stop_notify_calls = 0
            self.start_notify_targets: list[int | str] = []
            self.write_targets: list[int | str] = []
            self.write_responses: list[bool | None] = []
            self._notify_handler: Callable[[object | None, bytes], None] | None = None
            self.services = [
                DummyService(
                    "0000ffd0-0000-1000-8000-00805f9b34fb",
                    [
                        DummyCharacteristic(
                            "0000ffd1-0000-1000-8000-00805f9b34fb",
                            17,
                            write_properties,
                        )
                    ],
                ),
                DummyService(
                    "0000fff0-0000-1000-8000-00805f9b34fb",
                    [
                        DummyCharacteristic(
                            "0000fff1-0000-1000-8000-00805f9b34fb",
                            33,
                            ["notify"],
                        )
                    ],
                ),
            ]

        async def start_notify(self, target, callback):
            self.start_notify_targets.append(target)
            self._notify_handler = callback

        async def write_gatt_char(self, target, payload, response=None):
            if self._notify_handler is None:
                raise AssertionError("Notify handler was not set.")

            request = bytes(payload)
            self.write_targets.append(target)
            self.write_responses.append(response)
            register = int.from_bytes(request[2:4], "big")

            def _frame(device_id: int, payload_bytes: bytes) -> bytes:
                frame = bytearray([device_id, 0x03, len(payload_bytes)])
                frame.extend(payload_bytes)
                crc_low, crc_high = modbus_crc(frame)
                frame.extend([crc_low, crc_high])
                return bytes(frame)

            info_payload = bytearray(56)
            info_payload[12:28] = b"RENOGY-PRO-0002 "
            info_payload[36:52] = b"Pro Battery     "
            info_payload[52:56] = b"2.10"

            pack_payload = bytearray(14)
            pack_payload[0:2] = int(1234).to_bytes(2, "big", signed=True)
            pack_payload[2:4] = (512).to_bytes(2, "big")
            pack_payload[4:8] = (65000).to_bytes(4, "big")
            pack_payload[8:12] = (100000).to_bytes(4, "big")
            pack_payload[12:14] = (7).to_bytes(2, "big")

            cell_payload = bytearray(68)
            cell_payload[0:2] = (4).to_bytes(2, "big")
            for index, value in enumerate((33, 33, 33, 33)):
                start = 2 + index * 2
                cell_payload[start : start + 2] = value.to_bytes(2, "big")
            cell_payload[34:36] = (1).to_bytes(2, "big")
            cell_payload[36:38] = (230).to_bytes(2, "big", signed=True)

            mosfet_payload = bytearray(16)
            mosfet_payload[13] = 0x02

            responses = {
                0x13F0: _frame(0xFF, bytes(info_payload)),
                0x13B2: _frame(0xFF, bytes(pack_payload)),
                0x1388: _frame(0xFF, bytes(cell_payload)),
                0x13EC: _frame(0xFF, bytes(mosfet_payload)),
            }
            self._notify_handler(None, responses[register])

        async def stop_notify(self, target):
            self.stop_notify_calls += 1
            self.start_notify_targets.append(target)

        async def disconnect(self):
            self.disconnect_calls += 1
            self.is_connected = False

    dummy_client = DummyClient()

    async def _fake_establish_connection(*_args, **_kwargs):
        return dummy_client

    from renogy_ble import ble as ble_module

    monkeypatch.setattr(ble_module, "establish_connection", _fake_establish_connection)

    client = RenogyBleClient()
    device = RenogyBLEDevice(
        _mock_ble_device(name="RNGRBP123456"), device_type="battery"
    )

    result = asyncio.run(client.read_device(device))

    assert result.success is True
    assert result.parsed_data["battery_variant"] == BATTERY_VARIANT_PRO
    assert result.parsed_data["cell_voltages"] == [3.3, 3.3, 3.3, 3.3]
    assert dummy_client.start_notify_targets[0] == 33
    assert dummy_client.write_targets == [17] * 4
    assert dummy_client.write_responses == [expected_response] * 4


def test_read_device_falls_back_to_uuid_when_battery_services_do_not_all_match(
    monkeypatch,
):
    class DummyCharacteristic:
        def __init__(self, uuid: str, handle: int, properties: list[str]):
            self.uuid = uuid
            self.handle = handle
            self.properties = properties

    class DummyService:
        def __init__(self, uuid: str, characteristics: list[DummyCharacteristic]):
            self.uuid = uuid
            self.characteristics = characteristics

    class DummyClient:
        def __init__(self):
            self.is_connected = True
            self.disconnect_calls = 0
            self.stop_notify_calls = 0
            self.start_notify_targets: list[int | str] = []
            self.write_targets: list[int | str] = []
            self.write_responses: list[bool | None] = []
            self._notify_handler: Callable[[object | None, bytes], None] | None = None
            self.services = [
                DummyService(
                    "0000ffd0-0000-1000-8000-00805f9b34fb",
                    [
                        DummyCharacteristic(
                            "0000ffd1-0000-1000-8000-00805f9b34fb",
                            17,
                            ["write"],
                        )
                    ],
                ),
                DummyService(
                    "00005678-0000-1000-8000-00805f9b34fb",
                    [
                        DummyCharacteristic(
                            "0000fff1-0000-1000-8000-00805f9b34fb",
                            33,
                            ["notify"],
                        )
                    ],
                ),
            ]

        async def start_notify(self, target, callback):
            self.start_notify_targets.append(target)
            self._notify_handler = callback

        async def write_gatt_char(self, target, payload, response=None):
            if self._notify_handler is None:
                raise AssertionError("Notify handler was not set.")

            request = bytes(payload)
            self.write_targets.append(target)
            self.write_responses.append(response)
            register = int.from_bytes(request[2:4], "big")

            def _frame(device_id: int, payload_bytes: bytes) -> bytes:
                frame = bytearray([device_id, 0x03, len(payload_bytes)])
                frame.extend(payload_bytes)
                crc_low, crc_high = modbus_crc(frame)
                frame.extend([crc_low, crc_high])
                return bytes(frame)

            info_payload = bytearray(56)
            info_payload[12:28] = b"RENOGY-PRO-0002 "
            info_payload[36:52] = b"Pro Battery     "
            info_payload[52:56] = b"2.10"

            pack_payload = bytearray(14)
            pack_payload[0:2] = int(1234).to_bytes(2, "big", signed=True)
            pack_payload[2:4] = (512).to_bytes(2, "big")
            pack_payload[4:8] = (65000).to_bytes(4, "big")
            pack_payload[8:12] = (100000).to_bytes(4, "big")
            pack_payload[12:14] = (7).to_bytes(2, "big")

            cell_payload = bytearray(68)
            cell_payload[0:2] = (4).to_bytes(2, "big")
            for index, value in enumerate((33, 33, 33, 33)):
                start = 2 + index * 2
                cell_payload[start : start + 2] = value.to_bytes(2, "big")
            cell_payload[34:36] = (1).to_bytes(2, "big")
            cell_payload[36:38] = (230).to_bytes(2, "big", signed=True)

            mosfet_payload = bytearray(16)
            mosfet_payload[13] = 0x02

            responses = {
                0x13F0: _frame(0xFF, bytes(info_payload)),
                0x13B2: _frame(0xFF, bytes(pack_payload)),
                0x1388: _frame(0xFF, bytes(cell_payload)),
                0x13EC: _frame(0xFF, bytes(mosfet_payload)),
            }
            self._notify_handler(None, responses[register])

        async def stop_notify(self, target):
            self.stop_notify_calls += 1
            self.start_notify_targets.append(target)

        async def disconnect(self):
            self.disconnect_calls += 1
            self.is_connected = False

    dummy_client = DummyClient()

    async def _fake_establish_connection(*_args, **_kwargs):
        return dummy_client

    from renogy_ble import ble as ble_module

    monkeypatch.setattr(ble_module, "establish_connection", _fake_establish_connection)

    client = RenogyBleClient()
    device = RenogyBLEDevice(
        _mock_ble_device(name="RNGRBP123456"), device_type="battery"
    )

    result = asyncio.run(client.read_device(device))

    assert result.success is True
    assert result.parsed_data["battery_variant"] == BATTERY_VARIANT_PRO
    assert result.parsed_data["cell_voltages"] == [3.3, 3.3, 3.3, 3.3]
    assert dummy_client.start_notify_targets[0] == RENOGY_READ_CHAR_UUID
    assert dummy_client.write_targets == [RENOGY_WRITE_CHAR_UUID] * 4
    assert dummy_client.write_responses == [True] * 4


def test_read_device_battery_stops_after_command_timeout(monkeypatch):
    class DummyClient:
        def __init__(self):
            self.is_connected = True
            self.disconnect_calls = 0
            self.stop_notify_calls = 0
            self.writes: list[bytes] = []
            self._notify_handler: Callable[[object | None, bytes], None] | None = None

        async def start_notify(self, *_args, **_kwargs):
            self._notify_handler = _args[1]

        async def write_gatt_char(self, _uuid, payload, response=None):
            self.writes.append(bytes(payload))

        async def stop_notify(self, *_args, **_kwargs):
            self.stop_notify_calls += 1

        async def disconnect(self):
            self.disconnect_calls += 1
            self.is_connected = False

    def _battery_frame(device_id: int, payload_bytes: bytes) -> bytes:
        frame = bytearray([device_id, 0x03, len(payload_bytes)])
        frame.extend(payload_bytes)
        crc_low, crc_high = modbus_crc(frame)
        frame.extend([crc_low, crc_high])
        return bytes(frame)

    info_payload = bytearray(56)
    info_payload[12:28] = b"RENOGY-BAT-0001 "
    info_payload[36:52] = b"House Battery 1 "
    info_payload[52:56] = b"1.02"

    pack_payload = bytearray(14)
    pack_payload[0:2] = int(1234).to_bytes(2, "big", signed=True)
    pack_payload[2:4] = (512).to_bytes(2, "big")
    pack_payload[4:8] = (50000).to_bytes(4, "big")
    pack_payload[8:12] = (100000).to_bytes(4, "big")
    pack_payload[12:14] = (42).to_bytes(2, "big")

    mosfet_payload = bytearray(16)
    mosfet_payload[13] = 0x16
    mosfet_payload[14] = 0x20

    responses = {
        "battery device_info": _battery_frame(0x30, bytes(info_payload)),
        "battery pack_status": _battery_frame(0x30, bytes(pack_payload)),
        "battery mosfet_status": _battery_frame(0x30, bytes(mosfet_payload)),
    }

    dummy_client = DummyClient()

    async def _fake_establish_connection(*_args, **_kwargs):
        return dummy_client

    async def _fake_wait_for_valid_read_response(
        _session,
        *,
        cmd_name,
        **_kwargs,
    ):
        if cmd_name == "battery cell_status":
            _session.desynchronized = True
            raise asyncio.TimeoutError()

        return responses[cmd_name]

    from renogy_ble import ble as ble_module

    monkeypatch.setattr(ble_module, "establish_connection", _fake_establish_connection)

    client = RenogyBleClient()
    monkeypatch.setattr(
        client,
        "_wait_for_valid_read_response",
        _fake_wait_for_valid_read_response,
    )
    device = RenogyBLEDevice(
        _mock_ble_device(name="BT-TH-BATT01"), device_type="battery"
    )

    result = asyncio.run(client.read_device(device))

    assert result.success is True
    assert result.error is None
    assert result.parsed_data["battery_variant"] == BATTERY_VARIANT_LEGACY
    assert result.parsed_data["battery_voltage"] == 51.2
    assert result.parsed_data["battery_current"] == 12.34
    assert "battery_temperature" not in result.parsed_data
    assert device.name == "House Battery 1"
    # The poll stops at the timed-out command rather than issuing mosfet_status,
    # because a late reply could be misread as that command's response.
    assert "charge_mosfet_enabled" not in result.parsed_data
    assert len(dummy_client.writes) == 3
    assert dummy_client.stop_notify_calls == 1
    assert dummy_client.disconnect_calls == 1


def test_read_device_battery_drops_stale_partial_poll_data(monkeypatch):
    class DummyClient:
        def __init__(self):
            self.is_connected = True
            self.disconnect_calls = 0
            self.start_notify_calls = 0
            self.stop_notify_calls = 0
            self.writes: list[bytes] = []
            self._notify_handler: Callable[[object | None, bytes], None] | None = None

        async def start_notify(self, *_args, **_kwargs):
            self.start_notify_calls += 1
            self._notify_handler = _args[1]

        async def write_gatt_char(self, _uuid, payload, response=None):
            self.writes.append(bytes(payload))

        async def stop_notify(self, *_args, **_kwargs):
            self.stop_notify_calls += 1

        async def disconnect(self):
            self.disconnect_calls += 1
            self.is_connected = False

    def _battery_frame(device_id: int, payload_bytes: bytes) -> bytes:
        frame = bytearray([device_id, 0x03, len(payload_bytes)])
        frame.extend(payload_bytes)
        crc_low, crc_high = modbus_crc(frame)
        frame.extend([crc_low, crc_high])
        return bytes(frame)

    info_payload = bytearray(56)
    info_payload[12:28] = b"RENOGY-BAT-0001 "
    info_payload[36:52] = b"House Battery 1 "
    info_payload[52:56] = b"1.02"

    pack_payload = bytearray(14)
    pack_payload[0:2] = int(1234).to_bytes(2, "big", signed=True)
    pack_payload[2:4] = (512).to_bytes(2, "big")
    pack_payload[4:8] = (50000).to_bytes(4, "big")
    pack_payload[8:12] = (100000).to_bytes(4, "big")
    pack_payload[12:14] = (42).to_bytes(2, "big")

    cell_payload = bytearray(68)
    cell_payload[0:2] = (4).to_bytes(2, "big")
    for index, value in enumerate((330, 329, 331, 332)):
        start = 2 + index * 2
        cell_payload[start : start + 2] = value.to_bytes(2, "big")
    cell_payload[34:36] = (2).to_bytes(2, "big")
    cell_payload[36:38] = (215).to_bytes(2, "big", signed=True)
    cell_payload[38:40] = (225).to_bytes(2, "big", signed=True)

    mosfet_payload = bytearray(16)
    mosfet_payload[13] = 0x16
    mosfet_payload[14] = 0x20

    responses = {
        "battery device_info": _battery_frame(0x30, bytes(info_payload)),
        "battery pack_status": _battery_frame(0x30, bytes(pack_payload)),
        "battery cell_status": _battery_frame(0x30, bytes(cell_payload)),
        "battery mosfet_status": _battery_frame(0x30, bytes(mosfet_payload)),
    }

    dummy_client = DummyClient()
    poll_number = 0

    async def _fake_establish_connection(*_args, **_kwargs):
        return dummy_client

    async def _fake_wait_for_valid_read_response(
        _session,
        *,
        cmd_name,
        **_kwargs,
    ):
        if poll_number == 1 and cmd_name in {
            "battery cell_status",
            "battery mosfet_status",
        }:
            raise asyncio.TimeoutError()

        return responses[cmd_name]

    from renogy_ble import ble as ble_module

    monkeypatch.setattr(ble_module, "establish_connection", _fake_establish_connection)

    client = RenogyBleClient(transport_mode="persistent_session")
    monkeypatch.setattr(
        client,
        "_wait_for_valid_read_response",
        _fake_wait_for_valid_read_response,
    )
    device = RenogyBLEDevice(
        _mock_ble_device(name="BT-TH-BATT01"), device_type="battery"
    )

    async def _run() -> tuple[dict[str, object], dict[str, object]]:
        nonlocal poll_number
        first = await client.read_device(device)
        poll_number = 1
        second = await client.read_device(device)
        await client.close_device(device)
        return first.parsed_data, second.parsed_data

    first_data, second_data = asyncio.run(_run())

    assert first_data["battery_temperature"] == 22.0
    assert first_data["charge_mosfet_enabled"] is True
    assert second_data["battery_voltage"] == 51.2
    assert second_data["battery_current"] == 12.34
    assert second_data["serial_number"] == "RENOGY-BAT-0001"
    assert second_data["sw_version"] == "1.02"
    assert "battery_temperature" not in second_data
    assert "cell_count" not in second_data
    assert "charge_mosfet_enabled" not in second_data
    assert "discharge_mosfet_enabled" not in second_data
    assert "heater_enabled" not in second_data


def test_read_device_battery_clears_stale_telemetry_after_reconnect_failure(
    monkeypatch,
):
    class DummyClient:
        def __init__(self):
            self.is_connected = False
            self.disconnect_calls = 0

        async def disconnect(self):
            self.disconnect_calls += 1

    dummy_client = DummyClient()

    async def _fake_establish_connection(*_args, **_kwargs):
        return dummy_client

    from renogy_ble import ble as ble_module

    monkeypatch.setattr(ble_module, "establish_connection", _fake_establish_connection)

    client = RenogyBleClient()
    device = RenogyBLEDevice(
        _mock_ble_device(name="BT-TH-BATT01"), device_type="battery"
    )
    device.parsed_data = {
        "serial_number": "RENOGY-BAT-0001",
        "sw_version": "1.02",
        "battery_variant": BATTERY_VARIANT_LEGACY,
        "model": "Renogy Bluetooth Battery",
        "battery_voltage": 51.2,
        "battery_current": 12.34,
    }

    result = asyncio.run(client.read_device(device))

    assert result.success is False
    assert result.error is not None
    assert result.parsed_data == {
        "serial_number": "RENOGY-BAT-0001",
        "sw_version": "1.02",
        "battery_variant": BATTERY_VARIANT_LEGACY,
        "model": "Renogy Bluetooth Battery",
    }
    assert device.parsed_data == result.parsed_data


def test_read_device_inverter_preserves_cached_metadata_in_persistent_session(
    monkeypatch,
):
    class DummyClient:
        def __init__(self):
            self.is_connected = True
            self.disconnect_calls = 0
            self.start_notify_calls = 0
            self.stop_notify_calls = 0
            self.read_gatt_char_calls = 0
            self.writes: list[bytes] = []
            self._notify_handler: Callable[[object | None, bytes], None] | None = None

        async def start_notify(self, *_args, **_kwargs):
            self.start_notify_calls += 1
            self._notify_handler = _args[1]

        async def write_gatt_char(self, _uuid, payload, response=None):
            if self._notify_handler is None:
                raise AssertionError("Notify handler was not set.")

            request = bytes(payload)
            self.writes.append(request)
            register = int.from_bytes(request[2:4], "big")
            responses = {
                4000: _modbus_read_response(
                    INVERTER_DEVICE_ID,
                    [2300, 100, 2290, 200, 6000, 402, 260, 0, 0, 6000],
                ),
                4408: _modbus_read_response(
                    INVERTER_DEVICE_ID, [150, 450, 475, 0, 0, 0]
                ),
                4327: _modbus_read_response(
                    INVERTER_DEVICE_ID, [80, 65526, 1200, 30, 360, 1, 360]
                ),
                4456: _modbus_read_response(INVERTER_DEVICE_ID, [200]),
                4422: _modbus_read_response(INVERTER_DEVICE_ID, [1500]),
                4430: _modbus_read_response(INVERTER_DEVICE_ID, [120]),
                4452: _modbus_read_response(INVERTER_DEVICE_ID, [158]),
            }
            self._notify_handler(None, responses[register])

        async def read_gatt_char(self, *_args, **_kwargs):
            self.read_gatt_char_calls += 1
            return b"\x00"

        async def stop_notify(self, *_args, **_kwargs):
            self.stop_notify_calls += 1

        async def disconnect(self):
            self.disconnect_calls += 1
            self.is_connected = False

    dummy_client = DummyClient()
    establish_calls = 0

    async def _fake_establish_connection(*_args, **_kwargs):
        nonlocal establish_calls
        establish_calls += 1
        dummy_client.is_connected = True
        return dummy_client

    from renogy_ble import ble as ble_module

    monkeypatch.setattr(ble_module, "establish_connection", _fake_establish_connection)

    client = RenogyBleClient(transport_mode="persistent_session")
    device = RenogyBLEDevice(
        _mock_ble_device(name="RNGRIU123456"), device_type="inverter"
    )
    device.parsed_data = {"device_id": 32, "model": "RIV1220PU-126"}

    async def _run() -> tuple[dict[str, object], dict[str, object]]:
        first = await client.read_device(device)
        second = await client.read_device(device)
        await client.close_device(device)
        return first.parsed_data, second.parsed_data

    first_data, second_data = asyncio.run(_run())

    assert establish_calls == 1
    assert dummy_client.start_notify_calls == 1
    assert dummy_client.stop_notify_calls == 1
    assert dummy_client.disconnect_calls == 1
    assert dummy_client.read_gatt_char_calls == 2
    assert [int.from_bytes(request[2:4], "big") for request in dummy_client.writes] == [
        4000,
        4408,
        4327,
        4456,
        4422,
        4430,
        4452,
        4000,
        4408,
        4327,
        4456,
        4422,
        4430,
        4452,
    ]
    assert first_data["device_id"] == 32
    assert first_data["model"] == "RIV1220PU-126"
    assert first_data["inverter_ac_input_current_limit"] == pytest.approx(20.0)
    assert first_data["inverter_charge_current"] == pytest.approx(150.0)
    assert first_data["inverter_low_voltage_warn"] == pytest.approx(12.0)
    assert first_data["inverter_over_voltage"] == pytest.approx(15.8)
    assert second_data["device_id"] == 32
    assert second_data["model"] == "RIV1220PU-126"
    assert second_data["inverter_ac_input_current_limit"] == pytest.approx(20.0)
    assert second_data["inverter_charge_current"] == pytest.approx(150.0)
    assert second_data["inverter_low_voltage_warn"] == pytest.approx(12.0)
    assert second_data["inverter_over_voltage"] == pytest.approx(15.8)


def test_persistent_session_reuses_connection_for_reads(monkeypatch):
    class DummyClient:
        def __init__(self):
            self.is_connected = True
            self.disconnect_calls = 0
            self.start_notify_calls = 0
            self.stop_notify_calls = 0
            self._notify_handler: Callable[[object | None, bytes], None] | None = None

        async def start_notify(self, *_args, **_kwargs):
            self.start_notify_calls += 1
            self._notify_handler = _args[1]

        async def write_gatt_char(self, *_args, **_kwargs):
            if self._notify_handler is None:
                raise AssertionError("Notify handler was not set.")
            payload = bytes([DEFAULT_DEVICE_ID, 0x03, 0x02, 0x00, 0x00])
            crc_low, crc_high = modbus_crc(payload)
            self._notify_handler(None, payload + bytes([crc_low, crc_high]))

        async def stop_notify(self, *_args, **_kwargs):
            self.stop_notify_calls += 1

        async def disconnect(self):
            self.disconnect_calls += 1
            self.is_connected = False

    dummy_client = DummyClient()
    establish_calls = 0

    async def _fake_establish_connection(*_args, **_kwargs):
        nonlocal establish_calls
        establish_calls += 1
        dummy_client.is_connected = True
        return dummy_client

    from renogy_ble import ble as ble_module

    monkeypatch.setattr(ble_module, "establish_connection", _fake_establish_connection)

    client = RenogyBleClient(
        commands={"test_device": {"status": (3, 0x0000, 1)}},
        transport_mode="persistent_session",
    )
    device = RenogyBLEDevice(_mock_ble_device(), device_type="test_device")

    def _update_parsed_data(
        _raw_data: bytes, register: int, cmd_name: str = "unknown"
    ) -> bool:
        _ = register, cmd_name
        return True

    monkeypatch.setattr(device, "update_parsed_data", _update_parsed_data)

    async def _run() -> tuple[bool, bool]:
        first = await client.read_device(device)
        second = await client.read_device(device)
        await client.close_device(device)
        return first.success, second.success

    first_success, second_success = asyncio.run(_run())

    assert first_success is True
    assert second_success is True
    assert establish_calls == 1
    assert dummy_client.start_notify_calls == 1
    assert dummy_client.stop_notify_calls == 1
    assert dummy_client.disconnect_calls == 1


def test_read_device_stops_after_read_timeout_instead_of_misreading_reply(monkeypatch):
    """A late reply must not be attributed to the command that follows it.

    Modbus read responses carry no register address, so a reply that arrives
    after its own command timed out is indistinguishable from the next
    command's reply whenever both read the same number of words. The DCC reads
    reverse_charging_voltage (0xE020) and solar_cutoff_current (0xE038) back to
    back and both are single-word, which made a 12.7 V reading surface as a
    solar cutoff current of 127.
    """

    def _single_word_frame(value: int) -> bytes:
        payload = bytes(
            [DEFAULT_DEVICE_ID, 0x03, 0x02, (value >> 8) & 0xFF, value & 0xFF]
        )
        crc_low, crc_high = modbus_crc(payload)
        return payload + bytes([crc_low, crc_high])

    class DummyClient:
        def __init__(self):
            self.is_connected = True
            self.disconnect_calls = 0
            self.stop_notify_calls = 0
            self.requested_registers: list[int] = []
            self._notify_handler: Callable[[object | None, bytes], None] | None = None

        async def start_notify(self, *_args, **_kwargs):
            self._notify_handler = _args[1]

        async def write_gatt_char(self, _uuid, payload):
            if self._notify_handler is None:
                raise AssertionError("Notify handler was not set.")

            register = (payload[2] << 8) | payload[3]
            self.requested_registers.append(register)

            if register == 57376:  # 0xE020: reply withheld, so the read times out.
                return
            if register == 57400:  # 0xE038: would be served 0xE020's late reply.
                self._notify_handler(None, _single_word_frame(127))
                return

            self._notify_handler(None, _single_word_frame(5000))

        async def stop_notify(self, *_args, **_kwargs):
            self.stop_notify_calls += 1

        async def disconnect(self):
            self.disconnect_calls += 1
            self.is_connected = False

    dummy_client = DummyClient()

    async def _fake_establish_connection(*_args, **_kwargs):
        return dummy_client

    from renogy_ble import ble as ble_module

    monkeypatch.setattr(ble_module, "establish_connection", _fake_establish_connection)

    client = RenogyBleClient(
        commands={
            "dcc": {
                "current_limit": (3, 57345, 1),
                "reverse_charging_voltage": (3, 57376, 1),
                "solar_cutoff_current": (3, 57400, 1),
            }
        },
        max_notification_wait_time=0.01,
    )
    device = RenogyBLEDevice(_mock_ble_device(name="BT-TH-DCC01"), device_type="dcc")

    result = asyncio.run(client.read_device(device))

    # 0xE020's late reply must never be decoded as a solar cutoff current.
    assert "solar_cutoff_current" not in result.parsed_data
    # The poll stops at the timeout, so the stale reply is never collected.
    assert dummy_client.requested_registers == [57345, 57376]
    # Data read before the timeout is kept.
    assert result.parsed_data["max_charging_current"] == 50.0
    assert dummy_client.disconnect_calls == 1


def test_read_timeout_reconnects_before_next_persistent_session_poll(monkeypatch):
    """A timed-out persistent session must not be reused by the next poll."""

    clients = []

    class DummyClient:
        def __init__(self, connection_number: int):
            self.connection_number = connection_number
            self.is_connected = True
            self.disconnect_calls = 0
            self.requested_registers: list[int] = []
            self._notify_handler: Callable[[object | None, bytes], None] | None = None

        async def start_notify(self, *_args, **_kwargs):
            self._notify_handler = _args[1]

        async def write_gatt_char(self, _uuid, payload):
            if self._notify_handler is None:
                raise AssertionError("Notify handler was not set.")

            register = (payload[2] << 8) | payload[3]
            self.requested_registers.append(register)

            if self.connection_number == 1:
                if self.requested_registers == [0]:
                    self._notify_handler(
                        None, _modbus_read_response(DEFAULT_DEVICE_ID, [100])
                    )
                elif self.requested_registers == [0, 1]:
                    return
                elif self.requested_registers == [0, 1, 0]:
                    # This is register 1's late reply. If the timed-out session
                    # is reused, it is indistinguishable from register 0's reply.
                    self._notify_handler(
                        None, _modbus_read_response(DEFAULT_DEVICE_ID, [200])
                    )
                else:
                    self._notify_handler(
                        None, _modbus_read_response(DEFAULT_DEVICE_ID, [400])
                    )
                return

            response_value = 300 if register == 0 else 400
            self._notify_handler(
                None, _modbus_read_response(DEFAULT_DEVICE_ID, [response_value])
            )

        async def stop_notify(self, *_args, **_kwargs):
            pass

        async def disconnect(self):
            self.disconnect_calls += 1
            self.is_connected = False

    async def _fake_establish_connection(*_args, **_kwargs):
        dummy_client = DummyClient(len(clients) + 1)
        clients.append(dummy_client)
        return dummy_client

    from renogy_ble import ble as ble_module

    monkeypatch.setattr(ble_module, "establish_connection", _fake_establish_connection)

    client = RenogyBleClient(
        commands={"test_device": {"first": (3, 0, 1), "second": (3, 1, 1)}},
        max_notification_wait_time=0.01,
        transport_mode="persistent_session",
    )
    device = RenogyBLEDevice(_mock_ble_device(), device_type="test_device")
    parsed_values: list[tuple[int, int]] = []

    def _update_parsed_data(
        raw_data: bytes, register: int, cmd_name: str = "unknown"
    ) -> bool:
        _ = cmd_name
        parsed_values.append((register, int.from_bytes(raw_data[3:5], "big")))
        return True

    monkeypatch.setattr(device, "update_parsed_data", _update_parsed_data)

    async def _run() -> tuple[RenogyBleReadResult, RenogyBleReadResult]:
        first = await client.read_device(device)
        second = await client.read_device(device)
        await client.close_device(device)
        return first, second

    first_result, second_result = asyncio.run(_run())

    assert first_result.success is True
    assert first_result.error is None
    assert second_result.success is True
    assert second_result.error is None
    assert len(clients) == 2
    assert clients[0].requested_registers == [0, 1]
    assert clients[0].disconnect_calls == 1
    assert clients[1].requested_registers == [0, 1]
    assert clients[1].disconnect_calls == 1
    assert parsed_values == [(0, 100), (0, 300), (1, 400)]


def test_read_device_uses_valid_frame_when_notification_has_prefixed_junk(monkeypatch):
    class DummyClient:
        def __init__(self):
            self.is_connected = True
            self.disconnect_calls = 0
            self.stop_notify_calls = 0
            self._notify_handler: Callable[[object | None, bytes], None] | None = None

        async def start_notify(self, *_args, **_kwargs):
            self._notify_handler = _args[1]

        async def write_gatt_char(self, *_args, **_kwargs):
            if self._notify_handler is None:
                raise AssertionError("Notify handler was not set.")
            payload = bytes([DEFAULT_DEVICE_ID, 0x03, 0x02, 0x12, 0x34])
            crc_low, crc_high = modbus_crc(payload)
            self._notify_handler(
                None,
                b"\x99\x88" + payload + bytes([crc_low, crc_high]),
            )

        async def stop_notify(self, *_args, **_kwargs):
            self.stop_notify_calls += 1

        async def disconnect(self):
            self.disconnect_calls += 1
            self.is_connected = False

    dummy_client = DummyClient()

    async def _fake_establish_connection(*_args, **_kwargs):
        return dummy_client

    from renogy_ble import ble as ble_module

    monkeypatch.setattr(ble_module, "establish_connection", _fake_establish_connection)

    client = RenogyBleClient(commands={"test_device": {"status": (3, 0x0000, 1)}})
    device = RenogyBLEDevice(_mock_ble_device(), device_type="test_device")
    parsed_frames: list[bytes] = []

    def _update_parsed_data(
        raw_data: bytes, register: int, cmd_name: str = "unknown"
    ) -> bool:
        _ = register, cmd_name
        parsed_frames.append(raw_data)
        return True

    monkeypatch.setattr(device, "update_parsed_data", _update_parsed_data)

    result = asyncio.run(client.read_device(device))
    payload = bytes([DEFAULT_DEVICE_ID, 0x03, 0x02, 0x12, 0x34])
    crc_low, crc_high = modbus_crc(payload)
    valid_frame = payload + bytes([crc_low, crc_high])

    assert result.success is True
    assert parsed_frames == [valid_frame]


def test_persistent_session_reuses_connection_for_writes(monkeypatch):
    class DummyClient:
        def __init__(self):
            self.is_connected = True
            self.disconnect_calls = 0
            self.start_notify_calls = 0
            self.stop_notify_calls = 0
            self._notify_handler: Callable[[object | None, bytes], None] | None = None

        async def start_notify(self, *_args, **_kwargs):
            self.start_notify_calls += 1
            self._notify_handler = _args[1]

        async def write_gatt_char(self, _uuid, payload, response=None):
            if self._notify_handler is None:
                raise AssertionError("Notify handler was not set.")
            self._notify_handler(None, bytes(payload))

        async def stop_notify(self, *_args, **_kwargs):
            self.stop_notify_calls += 1

        async def disconnect(self):
            self.disconnect_calls += 1
            self.is_connected = False

    dummy_client = DummyClient()
    establish_calls = 0

    async def _fake_establish_connection(*_args, **_kwargs):
        nonlocal establish_calls
        establish_calls += 1
        dummy_client.is_connected = True
        return dummy_client

    from renogy_ble import ble as ble_module

    monkeypatch.setattr(ble_module, "establish_connection", _fake_establish_connection)

    client = RenogyBleClient(transport_mode="persistent_session")
    device = RenogyBLEDevice(_mock_ble_device())

    async def _run() -> tuple[bool, bool]:
        first = await client.write_single_register(device, 0x010A, 0x0001)
        second = await client.write_single_register(device, 0x010A, 0x0000)
        await client.close()
        return first.success, second.success

    first_success, second_success = asyncio.run(_run())

    assert first_success is True
    assert second_success is True
    assert establish_calls == 1
    assert dummy_client.start_notify_calls == 1
    assert dummy_client.stop_notify_calls == 1
    assert dummy_client.disconnect_calls == 1


def test_read_device_cleans_up_when_notify_setup_raises_runtime_error(monkeypatch):
    class DummyClient:
        def __init__(self):
            self.is_connected = True
            self.disconnect_calls = 0
            self.stop_notify_calls = 0

        async def start_notify(self, *_args, **_kwargs):
            raise RuntimeError("notify setup failed")

        async def stop_notify(self, *_args, **_kwargs):
            self.stop_notify_calls += 1

        async def disconnect(self):
            self.disconnect_calls += 1
            self.is_connected = False

    dummy_client = DummyClient()

    async def _fake_establish_connection(*_args, **_kwargs):
        return dummy_client

    from renogy_ble import ble as ble_module

    monkeypatch.setattr(ble_module, "establish_connection", _fake_establish_connection)

    client = RenogyBleClient(
        commands={"test_device": {"status": (3, 0x0000, 1)}},
        transport_mode="persistent_session",
    )
    device = RenogyBLEDevice(_mock_ble_device(), device_type="test_device")

    result = asyncio.run(client.read_device(device))

    assert result.success is False
    assert isinstance(result.error, RuntimeError)
    assert str(result.error) == "notify setup failed"
    assert dummy_client.stop_notify_calls == 0
    assert dummy_client.disconnect_calls == 1


def test_write_single_register_cleans_up_when_notify_setup_raises_runtime_error(
    monkeypatch,
):
    class DummyClient:
        def __init__(self):
            self.is_connected = True
            self.disconnect_calls = 0
            self.stop_notify_calls = 0

        async def start_notify(self, *_args, **_kwargs):
            raise RuntimeError("notify setup failed")

        async def stop_notify(self, *_args, **_kwargs):
            self.stop_notify_calls += 1

        async def disconnect(self):
            self.disconnect_calls += 1
            self.is_connected = False

    dummy_client = DummyClient()

    async def _fake_establish_connection(*_args, **_kwargs):
        return dummy_client

    from renogy_ble import ble as ble_module

    monkeypatch.setattr(ble_module, "establish_connection", _fake_establish_connection)

    client = RenogyBleClient(transport_mode="persistent_session")
    device = RenogyBLEDevice(_mock_ble_device())

    result = asyncio.run(client.write_single_register(device, 0x010A, 0x0001))

    assert result.success is False
    assert isinstance(result.error, RuntimeError)
    assert str(result.error) == "notify setup failed"
    assert dummy_client.stop_notify_calls == 0
    assert dummy_client.disconnect_calls == 1


# ---------------------------------------------------------------------------
# CRC validation on read responses
# ---------------------------------------------------------------------------


def _make_read_frame(data_bytes: bytes) -> bytes:
    """Build a well-formed Modbus read-response frame with a correct CRC.

    Frame layout: [device_id, func_code, byte_count, <data_bytes>, crc_low, crc_high]
    """
    header = bytes([DEFAULT_DEVICE_ID, 0x03, len(data_bytes)])
    payload = header + data_bytes
    crc_low, crc_high = modbus_crc(payload)
    return payload + bytes([crc_low, crc_high])


def test_update_parsed_data_accepts_valid_crc(monkeypatch):
    """A frame whose CRC matches its content must be parsed and accepted."""
    frame = _make_read_frame(bytes([0x00, 0x50, 0x00, 0x00]))

    device = RenogyBLEDevice(_mock_ble_device(), device_type="controller")

    from renogy_ble import ble as ble_module

    monkeypatch.setattr(
        ble_module.RenogyParser,
        "parse",
        lambda *_args, **_kwargs: {"battery_voltage": 12.5},
    )

    result = device.update_parsed_data(frame, register=256, cmd_name="status")

    assert result is True
    assert device.parsed_data.get("battery_voltage") == 12.5


def test_update_parsed_data_rejects_corrupted_crc(monkeypatch):
    """A frame with a bad CRC must be rejected before the parser is ever called."""
    frame = _make_read_frame(bytes([0x00, 0x50, 0x00, 0x00]))

    # Flip the low CRC byte to produce a mismatch.
    bad_frame = frame[:-2] + bytes([frame[-2] ^ 0xFF, frame[-1]])

    device = RenogyBLEDevice(_mock_ble_device(), device_type="controller")

    from renogy_ble import ble as ble_module

    parse_called = []
    monkeypatch.setattr(
        ble_module.RenogyParser,
        "parse",
        lambda *_args, **_kwargs: (
            parse_called.append(True) or {"battery_voltage": 99999.0}
        ),
    )

    result = device.update_parsed_data(bad_frame, register=256, cmd_name="status")

    assert result is False
    assert parse_called == [], "Parser must not be called when CRC is invalid"
    assert "battery_voltage" not in device.parsed_data


def test_update_parsed_data_rejects_bit_flipped_payload(monkeypatch):
    """A bit-flip anywhere in the data bytes must be caught by the CRC check.

    This simulates the real-world scenario where BLE corruption turns a normal
    voltage register value into a kilovolt-range reading.
    """
    # 0x00 0x50 encodes 8.0 V (scale 0.1); 0xFF 0xFF would encode 6553.5 V.
    frame = _make_read_frame(bytes([0x00, 0x50, 0x00, 0x00]))

    # Flip the first data byte — the original CRC is now wrong.
    corrupted = bytearray(frame)
    corrupted[3] = 0xFF
    bad_frame = bytes(corrupted)

    device = RenogyBLEDevice(_mock_ble_device(), device_type="controller")
    device.parsed_data["battery_voltage"] = 13.0  # pre-existing valid reading

    from renogy_ble import ble as ble_module

    monkeypatch.setattr(
        ble_module.RenogyParser,
        "parse",
        # What the parser would return if corruption were not caught.
        lambda *_args, **_kwargs: {"battery_voltage": 6553.5},
    )

    result = device.update_parsed_data(bad_frame, register=256, cmd_name="status")

    assert result is False
    # The pre-existing valid reading must be preserved, not overwritten with garbage.
    assert device.parsed_data.get("battery_voltage") == 13.0


def _dcc_g6_dummy_client_and_requests():
    """Build a DummyClient that answers like an RBC50D1S-G6 charger."""
    requests: list[tuple[int, int]] = []

    class DummyClient:
        def __init__(self):
            self.is_connected = True
            self.disconnect_calls = 0
            self._notify_handler: Callable[[object | None, bytes], None] | None = None

        async def start_notify(self, *_args, **_kwargs):
            self._notify_handler = _args[1]

        async def write_gatt_char(self, _uuid, payload):
            if self._notify_handler is None:
                raise AssertionError("Notify handler was not set.")

            register = (payload[2] << 8) | payload[3]
            word_count = (payload[4] << 8) | payload[5]
            requests.append((register, word_count))

            if register == 12:
                self._notify_handler(
                    None,
                    _modbus_ascii_response(DEFAULT_DEVICE_ID, "RBC50D1S-G6", 8),
                )
            elif register == 256:
                # 34-word dynamic_data with the status tail: 0x0120 low byte
                # carries charging_status 2 (mppt), 0x0121 carries fault_high.
                words = [0] * word_count
                if word_count >= 34:
                    words[32] = 0x0002
                    words[33] = 0x0000
                self._notify_handler(
                    None, _modbus_read_response(DEFAULT_DEVICE_ID, words)
                )
            elif register == 57345:
                self._notify_handler(
                    None, _modbus_read_response(DEFAULT_DEVICE_ID, [5000])
                )
            # register 288 (status) deliberately gets NO reply, like real G6
            # hardware -- reaching it at all is the regression this guards.

        async def stop_notify(self, *_args, **_kwargs):
            pass

        async def disconnect(self):
            self.disconnect_calls += 1
            self.is_connected = False

    return DummyClient(), requests


_DCC_TEST_COMMANDS = {
    "dcc": {
        "device_info": (3, 12, 8),
        "dynamic_data": (3, 256, 32),
        "status": (3, 288, 8),
        "current_limit": (3, 57345, 1),
    }
}


def test_g6_dcc_skips_status_and_reads_it_from_dynamic_data(monkeypatch):
    """A -G6 DCC must never be sent the status command it cannot answer.

    G6 firmware times out the discrete 0x0120 read; the timeout would abort
    every later command and tear down the session. The model parsed from
    device_info in the same poll must instead extend dynamic_data to 34 words
    and skip status entirely, with charging_status served from the tail.
    """
    dummy_client, requests = _dcc_g6_dummy_client_and_requests()

    async def _fake_establish_connection(*_args, **_kwargs):
        return dummy_client

    from renogy_ble import ble as ble_module

    monkeypatch.setattr(ble_module, "establish_connection", _fake_establish_connection)

    client = RenogyBleClient(
        commands=_DCC_TEST_COMMANDS,
        max_notification_wait_time=0.01,
    )
    device = RenogyBLEDevice(_mock_ble_device(name="BT-TH-A58A8FD4"), device_type="dcc")

    result = asyncio.run(client.read_device(device))

    requested_registers = [register for register, _words in requests]
    assert 288 not in requested_registers
    assert (256, 34) in requests
    assert result.parsed_data["model"] == "RBC50D1S-G6"
    assert result.parsed_data["charging_status"] == "mppt"
    assert result.parsed_data["fault_high"] == 0
    # Commands after "status" must still run -- on current code the status
    # timeout would have broken the loop before current_limit.
    assert result.parsed_data["max_charging_current"] == 50.0


def test_non_g6_dcc_keeps_discrete_status_read(monkeypatch):
    """A non-G6 DCC keeps the 32-word dynamic read and the status command."""
    dummy_client, requests = _dcc_g6_dummy_client_and_requests()

    async def _fake_establish_connection(*_args, **_kwargs):
        return dummy_client

    from renogy_ble import ble as ble_module

    monkeypatch.setattr(ble_module, "establish_connection", _fake_establish_connection)

    # Same frames, but the device identifies as a non-G6 DCC50S-family model.
    original_write = dummy_client.write_gatt_char

    async def _write(_uuid, payload):
        register = (payload[2] << 8) | payload[3]
        if register == 12:
            requests.append((register, (payload[4] << 8) | payload[5]))
            dummy_client._notify_handler(
                None,
                _modbus_ascii_response(DEFAULT_DEVICE_ID, "RBC2125DS-21W", 8),
            )
            return
        await original_write(_uuid, payload)

    dummy_client.write_gatt_char = _write

    client = RenogyBleClient(
        commands=_DCC_TEST_COMMANDS,
        max_notification_wait_time=0.01,
    )
    device = RenogyBLEDevice(_mock_ble_device(name="BT-TH-DCC01"), device_type="dcc")

    asyncio.run(client.read_device(device))

    assert (256, 32) in requests
    assert (288, 8) in requests
