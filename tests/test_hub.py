"""Tests for Communication Hub multi-battery discovery and polling."""

import asyncio
from typing import Callable
from unittest.mock import MagicMock

from renogy_ble.ble import RenogyBleClient, RenogyBLEDevice, modbus_crc
from renogy_ble.hub import HUB_BATTERY_SLAVE_IDS, RenogyCommunicationHub


def _mock_ble_device(
    name: str = "BT-TH-HUB",
    address: str = "AA:BB:CC:DD:EE:FF",
):
    device = MagicMock()
    device.name = name
    device.address = address
    device.rssi = -60
    return device


def _hub_status_frame(
    slave_id: int,
    *,
    voltage_tenths: int = 504,
    remaining_milliamp_hours: int = 49796,
    capacity_milliamp_hours: int = 49997,
) -> bytes:
    payload = bytearray()
    payload.extend((0x0146).to_bytes(2, "big"))
    payload.extend(voltage_tenths.to_bytes(2, "big"))
    payload.extend(remaining_milliamp_hours.to_bytes(4, "big"))
    payload.extend(capacity_milliamp_hours.to_bytes(4, "big"))

    frame = bytearray([slave_id, 0x03, len(payload)])
    frame.extend(payload)
    crc_low, crc_high = modbus_crc(frame)
    frame.extend([crc_low, crc_high])
    return bytes(frame)


class _DummyHubClient:
    def __init__(self, responders: dict[int, bytes]) -> None:
        self.is_connected = True
        self.responders = responders
        self.writes: list[bytes] = []
        self.disconnect_calls = 0
        self.stop_notify_calls = 0
        self._notify_handler: Callable[[object | None, bytes], None] | None = None

    async def start_notify(self, *_args, **_kwargs) -> None:
        self._notify_handler = _args[1]

    async def write_gatt_char(self, _uuid, payload) -> None:
        if self._notify_handler is None:
            raise AssertionError("Notify handler was not set")

        request = bytes(payload)
        self.writes.append(request)
        response = self.responders.get(request[0])
        if response is not None:
            self._notify_handler(None, response)

    async def stop_notify(self, *_args, **_kwargs) -> None:
        self.stop_notify_calls += 1

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        self.is_connected = False


def test_hub_discovers_multiple_slaves_and_caches_responders(monkeypatch) -> None:
    responders = {
        0x30: _hub_status_frame(0x30),
        0x31: _hub_status_frame(
            0x31,
            remaining_milliamp_hours=40842,
            capacity_milliamp_hours=49995,
        ),
        0x33: _hub_status_frame(
            0x33,
            remaining_milliamp_hours=45123,
            capacity_milliamp_hours=50001,
        ),
    }
    dummy_client = _DummyHubClient(responders)

    async def _fake_establish_connection(*_args, **_kwargs):
        dummy_client.is_connected = True
        return dummy_client

    from renogy_ble import ble as ble_module

    monkeypatch.setattr(ble_module, "establish_connection", _fake_establish_connection)

    client = RenogyBleClient(
        transport_mode="persistent_session",
        max_notification_wait_time=0.01,
    )
    hub = RenogyCommunicationHub(client, timeout=0.01)
    device = RenogyBLEDevice(_mock_ble_device(), device_type="inverter")

    async def _exercise():
        first = await hub.read_batteries(device)
        first_write_count = len(dummy_client.writes)
        second = await hub.read_batteries(device)
        second_writes = dummy_client.writes[first_write_count:]
        return first, second, second_writes

    first, second, second_writes = asyncio.run(_exercise())

    assert first.success is True
    assert first.error is None
    assert [battery.slave_id for battery in first.batteries] == [0x30, 0x31, 0x33]
    assert hub.discovered_slave_ids(device) == (0x30, 0x31, 0x33)
    assert [request[0] for request in dummy_client.writes[:8]] == list(
        HUB_BATTERY_SLAVE_IDS
    )
    assert dummy_client.disconnect_calls == 1

    assert second.success is True
    assert second.error is None
    assert [battery.slave_id for battery in second.batteries] == [0x30, 0x31, 0x33]
    assert [request[0] for request in second_writes] == [0x30, 0x31, 0x33]


def test_hub_rediscovery_finds_new_battery(monkeypatch) -> None:
    responders = {
        0x30: _hub_status_frame(0x30),
        0x31: _hub_status_frame(0x31),
    }
    dummy_client = _DummyHubClient(responders)

    async def _fake_establish_connection(*_args, **_kwargs):
        dummy_client.is_connected = True
        return dummy_client

    from renogy_ble import ble as ble_module

    monkeypatch.setattr(ble_module, "establish_connection", _fake_establish_connection)

    client = RenogyBleClient(
        transport_mode="persistent_session",
        max_notification_wait_time=0.01,
    )
    hub = RenogyCommunicationHub(client, timeout=0.01)
    device = RenogyBLEDevice(_mock_ble_device(), device_type="inverter")

    async def _exercise():
        initial = await hub.read_batteries(device)
        dummy_client.responders[0x32] = _hub_status_frame(0x32)
        before_rediscovery = len(dummy_client.writes)
        rediscovered = await hub.read_batteries(device, rediscover=True)
        rediscovery_writes = dummy_client.writes[before_rediscovery:]
        return initial, rediscovered, rediscovery_writes

    initial, rediscovered, rediscovery_writes = asyncio.run(_exercise())

    assert [battery.slave_id for battery in initial.batteries] == [0x30, 0x31]
    assert [battery.slave_id for battery in rediscovered.batteries] == [
        0x30,
        0x31,
        0x32,
    ]
    assert hub.discovered_slave_ids(device) == (0x30, 0x31, 0x32)
    assert [request[0] for request in rediscovery_writes] == list(HUB_BATTERY_SLAVE_IDS)


def test_hub_requests_are_read_only_pack_status_reads(monkeypatch) -> None:
    dummy_client = _DummyHubClient({0x30: _hub_status_frame(0x30)})

    async def _fake_establish_connection(*_args, **_kwargs):
        dummy_client.is_connected = True
        return dummy_client

    from renogy_ble import ble as ble_module

    monkeypatch.setattr(ble_module, "establish_connection", _fake_establish_connection)

    client = RenogyBleClient(max_notification_wait_time=0.01)
    hub = RenogyCommunicationHub(client, slave_ids=(0x30,), timeout=0.01)
    device = RenogyBLEDevice(_mock_ble_device(), device_type="inverter")

    result = asyncio.run(hub.read_batteries(device))

    assert result.success is True
    assert len(dummy_client.writes) == 1
    request = dummy_client.writes[0]
    assert request[:6] == bytes([0x30, 0x03, 0x13, 0xB2, 0x00, 0x06])
    assert "battery_current" not in result.batteries[0].parsed_data
    assert "battery_power" not in result.batteries[0].parsed_data


def test_hub_cached_timeout_preserves_discovery_and_drops_session(monkeypatch) -> None:
    responders = {
        0x30: _hub_status_frame(0x30),
        0x31: _hub_status_frame(0x31),
    }
    dummy_client = _DummyHubClient(responders)

    async def _fake_establish_connection(*_args, **_kwargs):
        dummy_client.is_connected = True
        return dummy_client

    from renogy_ble import ble as ble_module

    monkeypatch.setattr(ble_module, "establish_connection", _fake_establish_connection)

    client = RenogyBleClient(
        transport_mode="persistent_session",
        max_notification_wait_time=0.01,
    )
    hub = RenogyCommunicationHub(client, slave_ids=(0x30, 0x31), timeout=0.01)
    device = RenogyBLEDevice(_mock_ble_device(), device_type="inverter")

    async def _exercise():
        initial = await hub.read_batteries(device)
        del dummy_client.responders[0x31]
        disconnects_before = dummy_client.disconnect_calls
        result = await hub.read_batteries(device)
        return initial, disconnects_before, result

    initial, disconnects_before, result = asyncio.run(_exercise())

    assert initial.success is True
    assert hub.discovered_slave_ids(device) == (0x30, 0x31)
    assert result.success is True
    assert isinstance(result.error, asyncio.TimeoutError)
    assert [battery.slave_id for battery in result.batteries] == [0x30]
    assert hub.discovered_slave_ids(device) == (0x30, 0x31)
    assert dummy_client.disconnect_calls == disconnects_before + 1


def test_hub_empty_discovery_reports_no_batteries(monkeypatch) -> None:
    dummy_client = _DummyHubClient({})

    async def _fake_establish_connection(*_args, **_kwargs):
        dummy_client.is_connected = True
        return dummy_client

    from renogy_ble import ble as ble_module

    monkeypatch.setattr(ble_module, "establish_connection", _fake_establish_connection)

    client = RenogyBleClient(max_notification_wait_time=0.01)
    hub = RenogyCommunicationHub(client, slave_ids=(0x30, 0x31), timeout=0.01)
    device = RenogyBLEDevice(_mock_ble_device(), device_type="inverter")

    result = asyncio.run(hub.read_batteries(device))

    assert result.success is False
    assert result.batteries == []
    assert isinstance(result.error, RuntimeError)
    assert hub.discovered_slave_ids(device) == ()
