"""Regression tests for persistent-session GATT cache recovery."""

import asyncio
from unittest.mock import MagicMock

from bleak import BleakScanner
from bleak.exc import BleakCharacteristicNotFoundError, BleakError

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


def _bluez_device() -> RenogyBLEDevice:
    device = _device()
    device.ble_device.details = {"path": "/org/bluez/hci2/dev_AA_BB_CC_DD_EE_FF"}
    return device


def test_cache_clear_rediscovers_on_original_adapter_before_retry(monkeypatch):
    """Do not reconnect with the BlueZ handle removed by cache invalidation."""
    device = _bluez_device()
    original = device.ble_device
    refreshed = MagicMock()
    refreshed.address = device.address
    stale = DummyClient(fail_notify=True)
    fresh = DummyClient(fail_notify=False)
    removed = False
    connections = []
    scans = []

    async def establish(_class, handle, _name, **_kwargs):
        connections.append(handle)
        if removed:
            assert handle is refreshed, "Reused the removed BlueZ device"
            return fresh
        return stale

    async def clear(_address):
        nonlocal removed
        removed = True
        return True

    async def discover(address, **kwargs):
        scans.append((address, kwargs))
        assert stale.disconnect_calls == 1
        return refreshed

    monkeypatch.setattr(ble_module, "establish_connection", establish)
    monkeypatch.setattr(ble_module, "clear_cache", clear)
    monkeypatch.setattr(BleakScanner, "find_device_by_address", discover)
    client = RenogyBleClient(transport_mode="persistent_session")

    async def run():
        session = await client._prepare_session(device)
        await client._ensure_session_ready(device, session)
        assert session.notify_started
        await client.close_device(device)

    asyncio.run(run())
    assert connections == [original, refreshed]
    assert scans == [(device.address, {"adapter": "hci2"})]


def test_rediscovery_pending_survives_failed_poll(monkeypatch):
    """A later poll still waits for rediscovery instead of using a removed handle."""
    device = _bluez_device()
    original = device.ble_device
    refreshed = MagicMock()
    refreshed.address = device.address
    stale = DummyClient(fail_notify=True)
    fresh = DummyClient(fail_notify=False)
    connections = []
    scans = []
    discoveries = iter((None, refreshed))

    async def establish(_class, handle, _name, **_kwargs):
        connections.append(handle)
        return stale if len(connections) == 1 else fresh

    async def clear(_address):
        return True

    async def discover(_address, **kwargs):
        scans.append(kwargs)
        return next(discoveries)

    monkeypatch.setattr(ble_module, "establish_connection", establish)
    monkeypatch.setattr(ble_module, "clear_cache", clear)
    monkeypatch.setattr(BleakScanner, "find_device_by_address", discover)
    client = RenogyBleClient(transport_mode="persistent_session")

    async def run():
        session = await client._prepare_session(device)
        try:
            await client._ensure_session_ready(device, session)
        except BleakError:
            pass
        else:
            raise AssertionError("Should fail until the device reappears")
        await client.close_device(device)
        session = await client._prepare_session(device)
        await client._ensure_session_ready(device, session)
        assert session.notify_started
        await client.close_device(device)

    asyncio.run(run())
    assert connections == [original, refreshed]
    assert scans == [{"adapter": "hci2"}, {"adapter": "hci2"}]


def test_cancelled_cache_clear_disconnects_and_requires_rediscovery(monkeypatch):
    """Cancellation after invalidation must release the stale connection."""
    device = _bluez_device()
    stale = DummyClient(fail_notify=True)
    fresh = DummyClient(fail_notify=False)
    refreshed = MagicMock()
    connections = iter((stale, fresh))
    scans = []

    async def establish(*_args, **_kwargs):
        return next(connections)

    async def clear(_address):
        raise asyncio.CancelledError

    async def discover(address, **kwargs):
        scans.append((address, kwargs))
        return refreshed

    monkeypatch.setattr(ble_module, "establish_connection", establish)
    monkeypatch.setattr(ble_module, "clear_cache", clear)
    monkeypatch.setattr(BleakScanner, "find_device_by_address", discover)
    client = RenogyBleClient(transport_mode="persistent_session")

    async def run():
        session = await client._prepare_session(device)
        try:
            await client._ensure_session_ready(device, session)
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("Cancellation must propagate")
        assert stale.disconnect_calls == 1
        assert session.client is None
        await client._ensure_session_ready(device, session)
        await client.close_device(device)

    asyncio.run(run())
    assert scans == [(device.address, {"adapter": "hci2"})]


def test_other_notify_errors_do_not_clear_cache_or_retry(monkeypatch):
    """Only a missing characteristic should trigger destructive cache clearing."""
    device = _device()
    stale = DummyClient(fail_notify=False)
    calls = []

    async def establish(*_args, **_kwargs):
        calls.append("connect")
        return stale

    async def notify(*_args):
        raise BleakError("notification permission denied")

    async def clear(_address):
        raise AssertionError("Must not clear cache for other BLE errors")

    monkeypatch.setattr(stale, "start_notify", notify)
    monkeypatch.setattr(ble_module, "establish_connection", establish)
    monkeypatch.setattr(ble_module, "clear_cache", clear)
    client = RenogyBleClient(transport_mode="persistent_session")

    async def run():
        session = await client._prepare_session(device)
        try:
            await client._ensure_session_ready(device, session)
        except BleakError as exc:
            assert str(exc) == "notification permission denied"
        else:
            raise AssertionError("BLE error must propagate")
        await client.close_device(device)

    asyncio.run(run())
    assert calls == ["connect"]


def test_public_read_recovers_and_publishes_parsed_data(monkeypatch):
    """The public poll returns parsed telemetry after same-poll recovery."""
    device = _bluez_device()
    refreshed = MagicMock()
    stale = DummyClient(fail_notify=True)

    class TelemetryClient(DummyClient):
        async def start_notify(self, target, _callback):
            await super().start_notify(target, _callback)
            self.callback = _callback

        async def write_gatt_char(self, _target, request):
            assert int.from_bytes(request[2:4], "big") == 57348
            frame = b"\xff\x03\x02\x00\x02"
            self.callback(None, frame + bytes(ble_module.modbus_crc(frame)))

    fresh = TelemetryClient(fail_notify=False)
    connections = iter((stale, fresh))

    async def establish(*_args, **_kwargs):
        return next(connections)

    async def clear(_address):
        return True

    async def discover(*_args, **_kwargs):
        return refreshed

    monkeypatch.setattr(ble_module, "establish_connection", establish)
    monkeypatch.setattr(ble_module, "clear_cache", clear)
    monkeypatch.setattr(BleakScanner, "find_device_by_address", discover)
    client = RenogyBleClient(
        commands={"controller": {"battery": (3, 57348, 1)}},
        transport_mode="persistent_session",
    )

    async def run():
        result = await client.read_device(device)
        assert result.success
        assert result.error is None
        assert result.parsed_data == {"battery_type": "sealed"}
        await client.close_device(device)

    asyncio.run(run())
    assert stale.disconnect_calls == 1
    assert fresh.disconnect_calls == 1
