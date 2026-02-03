"""Tests for BLE helpers and device tracking."""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from renogy_ble.ble import (
    DEFAULT_DEVICE_ID,
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


def test_read_device_disconnects_even_if_not_connected(monkeypatch):
    class DummyClient:
        def __init__(self):
            self.is_connected = False
            self.disconnect_called = False

        async def start_notify(self, *_args, **_kwargs):
            raise BleakError("not connected")

        async def disconnect(self):
            self.disconnect_called = True

    dummy_client = DummyClient()

    async def _fake_establish_connection(*_args, **_kwargs):
        return dummy_client

    from renogy_ble import ble as ble_module

    monkeypatch.setattr(ble_module, "establish_connection", _fake_establish_connection)

    client = RenogyBleClient(commands={"test_device": {"status": (3, 0x0000, 1)}})
    device = RenogyBLEDevice(_mock_ble_device(), device_type="test_device")

    result = asyncio.run(client.read_device(device))

    assert result.success is False
    assert dummy_client.disconnect_called is True
