"""Regression tests for persistent-session GATT cache recovery."""

import asyncio
from unittest.mock import MagicMock

from bleak.exc import BleakCharacteristicNotFoundError

from renogy_ble import ble as ble_module
from renogy_ble.ble import RenogyBleClient, RenogyBLEDevice


class DummyClient:
    """Minimal connected BLE client used by stale-cache recovery tests."""

    def __init__(self, *, fail_notify: bool) -> None:
        self.fail_notify = fail_notify
        self.is_connected = True
        self.start_notify_calls = 0
        self.stop_notify_calls = 0
        self.disconnect_calls = 0

    async def start_notify(self, target, _callback) -> None:
        self.start_notify_calls += 1
        if self.fail_notify:
            raise BleakCharacteristicNotFoundError(target)

    async def stop_notify(self, _target) -> None:
        self.stop_notify_calls += 1

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        self.is_connected = False


def _device() -> RenogyBLEDevice:
    ble_device = MagicMock()
    ble_device.name = "BT-TH-TEST"
    ble_device.address = "AA:BB:CC:DD:EE:FF"
    return RenogyBLEDevice(ble_device, device_type="controller")


def test_persistent_session_clears_cache_and_recovers_in_same_poll(monkeypatch):
    """Clear stale services, reconnect once, and start notify on the fresh client."""
    stale_client = DummyClient(fail_notify=True)
    fresh_client = DummyClient(fail_notify=False)
    connections = iter((stale_client, fresh_client))
    establish_calls = 0
    cache_clear_calls: list[str] = []

    async def _fake_establish_connection(*_args, **_kwargs):
        nonlocal establish_calls
        establish_calls += 1
        return next(connections)

    async def _fake_clear_cache(address: str) -> bool:
        cache_clear_calls.append(address)
        return True

    monkeypatch.setattr(ble_module, "establish_connection", _fake_establish_connection)
    monkeypatch.setattr(ble_module, "clear_cache", _fake_clear_cache)

    device = _device()
    client = RenogyBleClient(transport_mode="persistent_session")

    async def _run() -> None:
        session = await client._prepare_session(device)
        await client._ensure_session_ready(device, session)
        assert session.client is fresh_client
        assert session.notify_started is True
        await client.close_device(device)

    asyncio.run(_run())

    assert establish_calls == 2
    assert cache_clear_calls == [device.address]
    assert stale_client.start_notify_calls == 1
    assert stale_client.disconnect_calls == 1
    assert fresh_client.start_notify_calls == 1
    assert fresh_client.stop_notify_calls == 1
    assert fresh_client.disconnect_calls == 1


def test_persistent_session_only_retries_missing_characteristic_once(monkeypatch):
    """Propagate a second missing-characteristic failure without retrying again."""
    first_client = DummyClient(fail_notify=True)
    second_client = DummyClient(fail_notify=True)
    connections = iter((first_client, second_client))
    establish_calls = 0
    cache_clear_calls: list[str] = []

    async def _fake_establish_connection(*_args, **_kwargs):
        nonlocal establish_calls
        establish_calls += 1
        return next(connections)

    async def _fake_clear_cache(address: str) -> bool:
        cache_clear_calls.append(address)
        return True

    monkeypatch.setattr(ble_module, "establish_connection", _fake_establish_connection)
    monkeypatch.setattr(ble_module, "clear_cache", _fake_clear_cache)

    device = _device()
    client = RenogyBleClient(transport_mode="persistent_session")

    async def _run() -> None:
        session = await client._prepare_session(device)
        try:
            await client._ensure_session_ready(device, session)
        except BleakCharacteristicNotFoundError:
            pass
        else:
            raise AssertionError("Expected missing characteristic to be propagated")
        await client.close_device(device)

    asyncio.run(_run())

    assert establish_calls == 2
    assert cache_clear_calls == [device.address]
    assert first_client.start_notify_calls == 1
    assert first_client.disconnect_calls == 1
    assert second_client.start_notify_calls == 1
    assert second_client.disconnect_calls == 1


def test_persistent_session_retries_when_cache_clear_returns_false(monkeypatch):
    """Reconnect even when no BlueZ service-cache entry was removed."""
    stale_client = DummyClient(fail_notify=True)
    fresh_client = DummyClient(fail_notify=False)
    connections = iter((stale_client, fresh_client))
    cache_clear_calls: list[str] = []

    async def _fake_establish_connection(*_args, **_kwargs):
        return next(connections)

    async def _fake_clear_cache(address: str) -> bool:
        cache_clear_calls.append(address)
        return False

    monkeypatch.setattr(ble_module, "establish_connection", _fake_establish_connection)
    monkeypatch.setattr(ble_module, "clear_cache", _fake_clear_cache)

    device = _device()
    client = RenogyBleClient(transport_mode="persistent_session")

    async def _run() -> None:
        session = await client._prepare_session(device)
        await client._ensure_session_ready(device, session)
        assert session.client is fresh_client
        assert session.notify_started is True
        await client.close_device(device)

    asyncio.run(_run())

    assert cache_clear_calls == [device.address]
    assert stale_client.disconnect_calls == 1
    assert fresh_client.start_notify_calls == 1


def test_persistent_session_retries_when_cache_clear_raises(monkeypatch):
    """Do not let a cache-clear failure mask the controlled reconnect and retry."""
    stale_client = DummyClient(fail_notify=True)
    fresh_client = DummyClient(fail_notify=False)
    connections = iter((stale_client, fresh_client))
    cache_clear_calls: list[str] = []

    async def _fake_establish_connection(*_args, **_kwargs):
        return next(connections)

    async def _fake_clear_cache(address: str) -> bool:
        cache_clear_calls.append(address)
        raise OSError("D-Bus cache invalidation failed")

    monkeypatch.setattr(ble_module, "establish_connection", _fake_establish_connection)
    monkeypatch.setattr(ble_module, "clear_cache", _fake_clear_cache)

    device = _device()
    client = RenogyBleClient(transport_mode="persistent_session")

    async def _run() -> None:
        session = await client._prepare_session(device)
        await client._ensure_session_ready(device, session)
        assert session.client is fresh_client
        assert session.notify_started is True
        await client.close_device(device)

    asyncio.run(_run())

    assert cache_clear_calls == [device.address]
    assert stale_client.disconnect_calls == 1
    assert fresh_client.start_notify_calls == 1
