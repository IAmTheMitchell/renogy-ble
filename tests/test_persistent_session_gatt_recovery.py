"""Regression tests for persistent-session GATT cache recovery."""

import asyncio
from unittest.mock import MagicMock

from bleak.exc import BleakCharacteristicNotFoundError

from renogy_ble import ble as ble_module
from renogy_ble.ble import RENOGY_READ_CHAR_UUID, RenogyBleClient, RenogyBLEDevice


def test_persistent_session_recovers_from_stale_gatt_cache(monkeypatch):
    """Reconnect once when a connected client cannot resolve the notify UUID."""

    class DummyClient:
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

    stale_client = DummyClient(fail_notify=True)
    fresh_client = DummyClient(fail_notify=False)
    connections = iter((stale_client, fresh_client))
    establish_calls = 0

    async def _fake_establish_connection(*_args, **_kwargs):
        nonlocal establish_calls
        establish_calls += 1
        return next(connections)

    monkeypatch.setattr(ble_module, "establish_connection", _fake_establish_connection)

    ble_device = MagicMock()
    ble_device.name = "BT-TH-TEST"
    ble_device.address = "AA:BB:CC:DD:EE:FF"
    device = RenogyBLEDevice(ble_device, device_type="controller")
    client = RenogyBleClient(transport_mode="persistent_session")

    async def _run() -> None:
        session = await client._prepare_session(device)
        await client._ensure_session_ready(device, session)
        assert session.client is fresh_client
        assert session.notify_started is True
        await client.close_device(device)

    asyncio.run(_run())

    assert establish_calls == 2
    assert stale_client.start_notify_calls == 1
    assert stale_client.disconnect_calls == 1
    assert fresh_client.start_notify_calls == 1
    assert fresh_client.stop_notify_calls == 1
    assert fresh_client.disconnect_calls == 1


def test_persistent_session_only_retries_missing_characteristic_once(monkeypatch):
    """Propagate a real missing-characteristic failure after one fresh reconnect."""

    class DummyClient:
        def __init__(self) -> None:
            self.is_connected = True
            self.start_notify_calls = 0
            self.disconnect_calls = 0

        async def start_notify(self, target, _callback) -> None:
            self.start_notify_calls += 1
            raise BleakCharacteristicNotFoundError(target)

        async def disconnect(self) -> None:
            self.disconnect_calls += 1
            self.is_connected = False

    first_client = DummyClient()
    second_client = DummyClient()
    connections = iter((first_client, second_client))

    async def _fake_establish_connection(*_args, **_kwargs):
        return next(connections)

    monkeypatch.setattr(ble_module, "establish_connection", _fake_establish_connection)

    ble_device = MagicMock()
    ble_device.name = "BT-TH-TEST"
    ble_device.address = "AA:BB:CC:DD:EE:FF"
    device = RenogyBLEDevice(ble_device, device_type="controller")
    client = RenogyBleClient(transport_mode="persistent_session")

    async def _run() -> None:
        session = await client._prepare_session(device)
        try:
            await client._ensure_session_ready(device, session)
        except BleakCharacteristicNotFoundError:
            pass
        else:
            raise AssertionError("Expected missing characteristic to be propagated")

    asyncio.run(_run())

    assert first_client.start_notify_calls == 1
    assert first_client.disconnect_calls == 1
    assert second_client.start_notify_calls == 1
