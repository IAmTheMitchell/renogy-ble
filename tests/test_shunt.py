"""Tests for Smart Shunt payload parsing."""

import asyncio
from unittest.mock import MagicMock

from bleak import BleakClient

from renogy_ble import shunt as shunt_module
from renogy_ble.ble import RenogyBLEDevice
from renogy_ble.shunt import (
    KEY_SHUNT_CURRENT,
    KEY_SHUNT_DECODE_CONFIDENCE,
    KEY_SHUNT_ENERGY_CHARGED_TOTAL,
    KEY_SHUNT_ENERGY_DISCHARGED_TOTAL,
    KEY_SHUNT_POWER,
    KEY_SHUNT_READING_VERIFIED,
    KEY_SHUNT_SOC,
    KEY_SHUNT_VOLTAGE,
    SHUNT_LIVE_HEADER,
    ShuntBleClient,
    _find_valid_payload_window,
    parse_shunt_payload,
)


def _build_payload(
    voltage: float = 13.2,
    current: float = -5.4,
    starter_voltage: float = 13.1,
    *,
    header: bytes = SHUNT_LIVE_HEADER,
    length: int = 110,
) -> bytes:
    """Build a synthetic 110-byte Smart Shunt payload."""
    payload = bytearray(length)
    payload[0 : len(header)] = header
    payload[25:28] = int(voltage * 1000).to_bytes(3, "big", signed=False)
    payload[21:24] = int(current * 1000).to_bytes(3, "big", signed=True)
    if length >= 32:
        payload[30:32] = int(starter_voltage * 1000).to_bytes(2, "big", signed=False)
    if length >= 36:
        payload[34:36] = int(85.4 * 10).to_bytes(2, "big", signed=False)
    if length >= 68:
        payload[66:68] = int(24.5 * 10).to_bytes(2, "big", signed=False)
    return bytes(payload)


def test_parse_shunt_payload_returns_expected_fields() -> None:
    """Validate parsing returns expected values for a valid payload."""
    data = parse_shunt_payload(_build_payload())

    assert data is not None
    assert data[KEY_SHUNT_VOLTAGE] == 13.2
    assert data[KEY_SHUNT_CURRENT] == -5.4
    assert data[KEY_SHUNT_POWER] == round(13.2 * -5.4, 2)
    assert data[KEY_SHUNT_SOC] == 85.4
    assert data[KEY_SHUNT_ENERGY_CHARGED_TOTAL] is None
    assert data[KEY_SHUNT_ENERGY_DISCHARGED_TOTAL] is None
    assert data[KEY_SHUNT_DECODE_CONFIDENCE] == "live_header"
    assert data[KEY_SHUNT_READING_VERIFIED] is True
    assert data["battery_temperature"] == 24.5


def test_parse_shunt_payload_rejects_non_live_header() -> None:
    """Validate non-live 4257 subtype frames are rejected."""
    data = parse_shunt_payload(_build_payload(header=bytes.fromhex("4257010b")))
    assert data is None


def test_parse_shunt_payload_rejects_out_of_range_voltage() -> None:
    """Validate obviously invalid voltage frames are rejected."""
    data = parse_shunt_payload(_build_payload(voltage=150.0))
    assert data is None


def test_parse_shunt_payload_rejects_unrealistically_low_voltage() -> None:
    """Validate unrealistically low battery voltages are rejected."""
    data = parse_shunt_payload(_build_payload(voltage=0.5))
    assert data is None


def test_parse_shunt_payload_rejects_short_payload() -> None:
    """Validate short payloads are rejected."""
    data = parse_shunt_payload(bytes([0x00] * 12))
    assert data is None


def test_parse_shunt_payload_accepts_short_live_frame() -> None:
    """Validate shorter live frames still parse when required fields exist."""
    data = parse_shunt_payload(_build_payload(voltage=12.8, current=3.1, length=28))

    assert data is not None
    assert data[KEY_SHUNT_VOLTAGE] == 12.8
    assert data[KEY_SHUNT_CURRENT] == 3.1
    assert data["battery_temperature"] is None


def test_find_valid_payload_window_recovers_from_misaligned_frame() -> None:
    """Validate parsing can recover when payload capture starts mid-frame."""
    valid_payload = _build_payload(voltage=13.2, current=4.3)
    stream = b"\xaa\xbb\xcc\xdd\xee" + valid_payload

    result = _find_valid_payload_window(stream, expected_length=110)

    assert result is not None
    raw_payload, parsed = result
    assert raw_payload == valid_payload
    assert parsed[KEY_SHUNT_VOLTAGE] == 13.2
    assert parsed[KEY_SHUNT_CURRENT] == 4.3


def test_find_valid_payload_window_prefers_live_frame_over_history_frame() -> None:
    """Validate history frames are skipped until a live payload is found."""
    history_payload = _build_payload(
        voltage=13.4, current=1.1, header=bytes.fromhex("4257010b")
    )
    live_payload = _build_payload(voltage=14.2, current=5.6)

    result = _find_valid_payload_window(
        history_payload + b"\xaa\xbb" + live_payload, expected_length=110
    )

    assert result is not None
    raw_payload, parsed = result
    assert raw_payload == live_payload
    assert parsed[KEY_SHUNT_VOLTAGE] == 14.2
    assert parsed[KEY_SHUNT_CURRENT] == 5.6


def test_find_valid_payload_window_strips_framed_live_packet() -> None:
    """Validate the parser strips the observed 61d2 framing prefix."""
    live_payload = _build_payload(voltage=13.9, current=2.4)
    framed_payload = bytes.fromhex("61d20000") + live_payload

    result = _find_valid_payload_window(framed_payload, expected_length=110)

    assert result is not None
    raw_payload, parsed = result
    assert raw_payload == live_payload
    assert parsed[KEY_SHUNT_VOLTAGE] == 13.9
    assert parsed[KEY_SHUNT_CURRENT] == 2.4


def test_find_valid_payload_window_supports_shorter_expected_length() -> None:
    """Validate the configurable expected length still works for shorter live frames."""
    live_payload = _build_payload(voltage=12.6, current=-1.8, length=28)

    result = _find_valid_payload_window(live_payload, expected_length=28)

    assert result is not None
    raw_payload, parsed = result
    assert raw_payload == live_payload
    assert parsed[KEY_SHUNT_VOLTAGE] == 12.6
    assert parsed[KEY_SHUNT_CURRENT] == -1.8


def test_energy_integration_tracks_totals_for_each_device_separately() -> None:
    """Validate energy totals are isolated per device address."""
    client = ShuntBleClient()

    assert client._integrate_energy_totals(
        device_address="A", power_w=100.0, now_ts=1000.0
    ) == (0, 0)
    assert client._integrate_energy_totals(
        device_address="B", power_w=200.0, now_ts=1100.0
    ) == (0, 0)

    a_charged, a_discharged = client._integrate_energy_totals(
        device_address="A", power_w=100.0, now_ts=4600.0
    )
    b_charged, b_discharged = client._integrate_energy_totals(
        device_address="B", power_w=-200.0, now_ts=2900.0
    )

    assert round(a_charged, 3) == 0.1
    assert round(a_discharged, 3) == 0
    assert round(b_charged, 3) == 0
    assert round(b_discharged, 3) == 0.1


def test_energy_integration_ignores_invalid_time_delta() -> None:
    """Validate energy totals do not accumulate for stale or non-positive deltas."""
    client = ShuntBleClient()

    assert client._integrate_energy_totals(
        device_address="A", power_w=50.0, now_ts=1000.0
    ) == (0, 0)
    assert client._integrate_energy_totals(
        device_address="A", power_w=50.0, now_ts=900.0
    ) == (0, 0)
    assert client._integrate_energy_totals(
        device_address="A", power_w=50.0, now_ts=50000.0
    ) == (0, 0)


def _mock_ble_device(name: str = "RTMShunt300A", address: str = "AA:BB:CC:DD:EE:FF"):
    """Create a minimal BLEDevice-like object for tests."""
    device = MagicMock()
    device.name = name
    device.address = address
    device.rssi = -60
    return device


def test_read_device_preserves_stale_data_on_connection_failure(monkeypatch) -> None:
    """Validate failed reads preserve the last known good parsed data."""
    connection_client_class = None
    connection_kwargs = None

    async def _fake_establish_connection(client_class, *_args, **_kwargs):
        nonlocal connection_client_class
        nonlocal connection_kwargs
        connection_client_class = client_class
        connection_kwargs = _kwargs
        raise asyncio.TimeoutError("connect timeout")

    monkeypatch.setattr(
        shunt_module, "establish_connection", _fake_establish_connection
    )

    client = ShuntBleClient()
    device = RenogyBLEDevice(_mock_ble_device(), device_type="SHUNT300")
    device.parsed_data = {"shunt_voltage": 13.2, "raw_payload": "stale"}

    result = asyncio.run(client.read_device(device))

    assert result.success is False
    assert isinstance(result.error, asyncio.TimeoutError)
    assert result.parsed_data == {"shunt_voltage": 13.2, "raw_payload": "stale"}
    assert device.parsed_data == {"shunt_voltage": 13.2, "raw_payload": "stale"}
    assert connection_client_class is BleakClient
    assert connection_kwargs is not None
    assert connection_kwargs["use_services_cache"] is False


def test_read_device_parses_misaligned_notification_stream(monkeypatch) -> None:
    """Validate read_device succeeds when first notification bytes are misaligned."""
    valid_payload = _build_payload(voltage=14.1, current=3.2)
    stream = b"\x01\x02\x03\x04\x05" + valid_payload

    class DummyClient:
        def __init__(self) -> None:
            self.is_connected = True
            self._notify_handler = None

        async def start_notify(self, _uuid, handler):
            self._notify_handler = handler
            self._notify_handler(1, bytearray(stream))

        async def stop_notify(self, *_args, **_kwargs):
            return None

        async def disconnect(self):
            self.is_connected = False

    async def _fake_establish_connection(*_args, **_kwargs):
        return DummyClient()

    monkeypatch.setattr(
        shunt_module, "establish_connection", _fake_establish_connection
    )

    client = ShuntBleClient()
    device = RenogyBLEDevice(_mock_ble_device(), device_type="SHUNT300")

    result = asyncio.run(client.read_device(device))

    assert result.success is True
    assert result.error is None
    assert result.parsed_data[KEY_SHUNT_VOLTAGE] == 14.1
    assert result.parsed_data[KEY_SHUNT_CURRENT] == 3.2


def test_read_device_preserves_last_good_data_on_history_only_payload(
    monkeypatch,
) -> None:
    """Validate non-live payloads do not overwrite the last good reading."""
    history_payload = _build_payload(
        voltage=14.8, current=4.1, header=bytes.fromhex("4257010b")
    )

    class DummyClient:
        def __init__(self) -> None:
            self.is_connected = True
            self._notify_handler = None

        async def start_notify(self, _uuid, handler):
            self._notify_handler = handler
            self._notify_handler(1, bytearray(history_payload))

        async def stop_notify(self, *_args, **_kwargs):
            return None

        async def disconnect(self):
            self.is_connected = False

    async def _fake_establish_connection(*_args, **_kwargs):
        return DummyClient()

    monkeypatch.setattr(
        shunt_module, "establish_connection", _fake_establish_connection
    )

    client = ShuntBleClient(max_notification_wait_time=0.01)
    device = RenogyBLEDevice(_mock_ble_device(), device_type="SHUNT300")
    device.parsed_data = {"shunt_voltage": 13.2, "raw_payload": "last-good"}

    result = asyncio.run(client.read_device(device))

    assert result.success is False
    assert isinstance(result.error, RuntimeError)
    assert result.parsed_data == {"shunt_voltage": 13.2, "raw_payload": "last-good"}
    assert device.parsed_data == {"shunt_voltage": 13.2, "raw_payload": "last-good"}
