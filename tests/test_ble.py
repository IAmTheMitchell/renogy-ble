"""Tests for BLE helpers and device tracking."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

from renogy_ble.ble import (
    DEFAULT_DEVICE_ID,
    UNAVAILABLE_RETRY_INTERVAL,
    RenogyBLEDevice,
    clean_device_name,
    create_modbus_read_request,
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
    assert (crc_low, crc_high) == (0x0A, 0x84)


def test_create_modbus_read_request_appends_crc():
    frame = create_modbus_read_request(DEFAULT_DEVICE_ID, 3, 0x0010, 2)
    assert frame[:6] == bytes([DEFAULT_DEVICE_ID, 3, 0x00, 0x10, 0x00, 0x02])
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
