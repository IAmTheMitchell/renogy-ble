"""Tests for BLE helpers and device tracking."""

import asyncio
import builtins
from datetime import datetime, timedelta
from typing import Callable
from unittest.mock import MagicMock

from renogy_ble.battery import BATTERY_VARIANT_LEGACY, BATTERY_VARIANT_PRO
from renogy_ble.ble import (
    DEFAULT_DEVICE_ID,
    INVERTER_DEVICE_ID,
    UNAVAILABLE_RETRY_INTERVAL,
    BleakError,
    RenogyBleClient,
    RenogyBLEDevice,
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

        async def write_gatt_char(self, _uuid, payload):
            if self._notify_handler is None:
                raise AssertionError("Notify handler was not set.")

            request = bytes(payload)
            self.writes.append(request)
            register = int.from_bytes(request[2:4], "big")
            responses = {
                4000: _modbus_read_response(
                    INVERTER_DEVICE_ID,
                    [2300, 125, 2295, 250, 6000, 401, 255, 0, 0, 5995] + ([0] * 22),
                ),
                4408: _modbus_read_response(
                    INVERTER_DEVICE_ID, [175, 500, 550, 0, 0, 0]
                ),
                4109: _modbus_read_response(INVERTER_DEVICE_ID, [32]),
                4311: _modbus_ascii_response(INVERTER_DEVICE_ID, "RIV1220PU-126", 8),
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
        "device_id": 32,
        "model": "RIV1220PU-126",
    }
    assert [request[0] for request in dummy_client.writes] == [INVERTER_DEVICE_ID] * 4
    assert dummy_client.stop_notify_calls == 1
    assert dummy_client.disconnect_calls == 1


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

        async def write_gatt_char(self, _uuid, payload):
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

        async def write_gatt_char(self, _uuid, payload):
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
            for index, value in enumerate((330, 330, 331, 331)):
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
    assert result.parsed_data["battery_temperature"] == 23.0
    assert [request[0] for request in dummy_client.writes] == [0xFF] * 4


def test_read_device_battery_continues_after_command_timeout(monkeypatch):
    class DummyClient:
        def __init__(self):
            self.is_connected = True
            self.disconnect_calls = 0
            self.stop_notify_calls = 0
            self.writes: list[bytes] = []
            self._notify_handler: Callable[[object | None, bytes], None] | None = None

        async def start_notify(self, *_args, **_kwargs):
            self._notify_handler = _args[1]

        async def write_gatt_char(self, _uuid, payload):
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
    assert result.parsed_data["charge_mosfet_enabled"] is True
    assert "battery_temperature" not in result.parsed_data
    assert device.name == "House Battery 1"
    assert len(dummy_client.writes) == 4
    assert dummy_client.stop_notify_calls == 1
    assert dummy_client.disconnect_calls == 1


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

        async def write_gatt_char(self, _uuid, payload):
            if self._notify_handler is None:
                raise AssertionError("Notify handler was not set.")

            request = bytes(payload)
            self.writes.append(request)
            register = int.from_bytes(request[2:4], "big")
            responses = {
                4000: _modbus_read_response(
                    INVERTER_DEVICE_ID,
                    [2300, 100, 2290, 200, 6000, 402, 260, 0, 0, 6000] + ([0] * 22),
                ),
                4408: _modbus_read_response(
                    INVERTER_DEVICE_ID, [150, 450, 475, 0, 0, 0]
                ),
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
        4000,
        4408,
    ]
    assert first_data["device_id"] == 32
    assert first_data["model"] == "RIV1220PU-126"
    assert second_data["device_id"] == 32
    assert second_data["model"] == "RIV1220PU-126"


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

        async def write_gatt_char(self, _uuid, payload):
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
