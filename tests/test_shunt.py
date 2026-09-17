"""Tests for Smart Shunt payload parsing."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
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
    ShuntNotificationDecoder,
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


@pytest.mark.parametrize("split", range(1, 110))
def test_decoder_reassembles_every_split(split):
    """All frame/header boundaries, including the reported 55/55 split, work."""
    payload = _build_payload()
    decoder = ShuntNotificationDecoder()
    assert decoder.feed(payload[:split]) == []
    readings = decoder.feed(payload[split:])
    assert len(readings) == 1
    assert readings[0]["shunt_voltage"] == 13.2
    assert readings[0]["shunt_current"] == -5.4
    assert readings[0]["shunt_soc"] == 85.4
    assert readings[0]["raw_payload"] == payload.hex()
    assert readings[0]["raw_words"] == [
        int.from_bytes(payload[i : i + 2], "big") for i in range(0, 110, 2)
    ]
    assert decoder.feed(b"") == []


def test_decoder_resynchronizes_and_returns_all_frames():
    """Noise, history, implausible live data and framing do not hide good data."""
    first = _build_payload(current=2)
    second = _build_payload(current=-3)
    stream = (
        b"noise"
        + _build_payload(header=bytes.fromhex("4257010b"))
        + _build_payload(voltage=150)
        + bytes.fromhex("61d20000")
        + first
        + second
        + first[:27]
    )
    decoder = ShuntNotificationDecoder()
    readings = decoder.feed(stream)
    assert [r["shunt_current"] for r in readings] == [2, -3]
    assert decoder.feed(first[27:])[0]["shunt_current"] == 2


def test_decoder_rejects_history_and_bounds_retained_noise():
    """Arbitrary invalid input cannot grow the retained stream indefinitely."""
    decoder = ShuntNotificationDecoder()
    assert decoder.feed(b"x" * 100000) == []
    assert len(decoder._buffer) < 110
    assert decoder.feed(_build_payload(header=bytes.fromhex("4257010b"))) == []
    assert decoder.feed(_build_payload())[0]["reading_verified"] is True


def test_decoder_reset_discards_partial_frame_and_retains_energy():
    """Reconnections cannot join old fragments but do retain device totals."""
    ticks = iter([1000, 4600, 8200])
    decoder = ShuntNotificationDecoder(clock=lambda: next(ticks))
    payload = _build_payload(voltage=10, current=10)
    assert decoder.feed(payload)[0]["energy_charged_total"] == 0
    assert decoder.feed(payload)[0]["energy_charged_total"] == 0.1
    assert decoder.feed(payload[:55]) == []
    decoder.reset_buffer()
    assert decoder.feed(payload[55:]) == []
    assert decoder.feed(payload)[0]["energy_charged_total"] == 0.2


def test_decoder_ignores_invalid_time_delta():
    """Non-positive deltas and gaps of ten hours or more add no energy."""
    ticks = iter([1000, 900, 50000])
    decoder = ShuntNotificationDecoder(clock=lambda: next(ticks))
    for _ in range(3):
        assert decoder.feed(_build_payload())[0]["energy_discharged_total"] == 0


def test_decoder_supports_configurable_frame_length():
    """The explicit shorter-frame override remains supported."""
    decoder = ShuntNotificationDecoder(expected_length=28)
    assert decoder.feed(_build_payload(length=28))[0]["shunt_voltage"] == 13.2
    with pytest.raises(ValueError):
        ShuntNotificationDecoder(expected_length=27)


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


class _Transport:
    """Transport fake that still exercises the real decoder and session."""

    def __init__(self, chunks=(), *, notify_error=None):
        self.is_connected = True
        self.chunks = chunks
        self.notify_error = notify_error
        self.started = asyncio.Event()
        self.handler = None
        self.stop_notify = AsyncMock()
        self.disconnect = AsyncMock(side_effect=self._disconnect)

    def _disconnect(self):
        self.is_connected = False

    async def start_notify(self, _uuid, handler):
        self.handler = handler
        for chunk in self.chunks:
            handler(1, bytearray(chunk))
        self.started.set()
        if self.notify_error:
            raise self.notify_error


def _device(address="A"):
    return RenogyBLEDevice(_mock_ble_device(address=address), device_type="SHUNT300")


def test_read_and_subscription_share_fragmented_decoding(monkeypatch):
    """Both real entry points normalize the reported fragmented payload equally."""

    async def scenario():
        payload = _build_payload()
        transports = [_Transport((payload[:55], payload[55:])) for _ in range(2)]
        monkeypatch.setattr(
            shunt_module, "establish_connection", AsyncMock(side_effect=transports)
        )
        monkeypatch.setattr(shunt_module, "clear_cache", AsyncMock(return_value=False))
        owner = ShuntBleClient()
        result = await owner.read_device(_device())
        assert result.success
        updates, errors = [], []
        sub = owner.subscribe(
            resolve_device=_device, on_update=updates.append, on_error=errors.append
        )
        task = asyncio.create_task(sub.run())
        await asyncio.wait_for(transports[1].started.wait(), 1)
        await sub.close()
        await sub.close()
        assert task.cancelled()
        assert updates == [result.parsed_data]
        assert errors == []
        for transport in transports:
            transport.stop_notify.assert_awaited_once()
            transport.disconnect.assert_awaited_once()
        with pytest.raises(RuntimeError):
            await sub.run()

    asyncio.run(scenario())


def test_energy_isolated_per_device_across_reads(monkeypatch):
    """One public client retains independent energy counters between read sessions."""

    async def scenario():
        ticks = iter([1000, 1100, 4600, 2900])
        # Resolve the clock at construction without changing asyncio's own clock.
        real_decoder = ShuntNotificationDecoder
        monkeypatch.setattr(
            shunt_module,
            "ShuntNotificationDecoder",
            lambda **kwargs: real_decoder(clock=lambda: next(ticks), **kwargs),
        )
        transports = [
            _Transport((_build_payload(voltage=10, current=current),))
            for current in (10, 20, 10, -20)
        ]
        monkeypatch.setattr(
            shunt_module, "establish_connection", AsyncMock(side_effect=transports)
        )
        owner = ShuntBleClient()
        for address in ("A", "B"):
            result = await owner.read_device(_device(address))
            assert result.parsed_data["energy_charged_total"] == 0
        a = await owner.read_device(_device("A"))
        b = await owner.read_device(_device("B"))
        assert a.parsed_data["energy_charged_total"] == 0.1
        assert a.parsed_data["energy_discharged_total"] == 0
        assert b.parsed_data["energy_charged_total"] == 0
        assert b.parsed_data["energy_discharged_total"] == 0.1

    asyncio.run(scenario())


def test_subscription_reconnect_resets_buffer_and_ignores_old_callbacks(monkeypatch):
    """A new connection cannot finish a partial frame from the disconnected one."""

    async def scenario():
        payload = _build_payload()
        first, second = _Transport((payload[:55],)), _Transport((payload[55:],))
        connections = []

        async def connect(*_args, **kwargs):
            connections.append(kwargs)
            return (first, second)[len(connections) - 1]

        monkeypatch.setattr(shunt_module, "establish_connection", connect)
        monkeypatch.setattr(shunt_module, "clear_cache", AsyncMock(return_value=False))
        updates, errors = [], []
        sub = ShuntBleClient().subscribe(
            resolve_device=_device,
            on_update=updates.append,
            on_error=errors.append,
            reconnect_delay=0,
        )
        task = asyncio.create_task(sub.run())
        await asyncio.wait_for(first.started.wait(), 1)
        first.is_connected = False
        connections[0]["disconnected_callback"](first)
        await asyncio.wait_for(second.started.wait(), 1)
        assert updates == []
        assert first.handler is not None
        first.handler(1, bytearray(payload))
        assert updates == []
        assert second.handler is not None
        second.handler(1, bytearray(payload + payload))
        assert len(updates) == 2
        assert len(errors) == 1
        assert "disconnected" in str(errors[0])
        await sub.close()
        assert task.done()
        first.disconnect.assert_awaited_once()
        second.disconnect.assert_awaited_once()
        assert all(c["use_services_cache"] is False for c in connections)

    asyncio.run(scenario())


@pytest.mark.parametrize("cache_result", [True, False, RuntimeError("no BlueZ")])
def test_subscription_cache_recovery(monkeypatch, cache_result):
    """Successful cache clears use a fresh handle; other backends still connect."""

    async def scenario():
        device = _device()
        original = device.ble_device
        fresh = _mock_ble_device(address="A")
        transport = _Transport()
        rediscover = MagicMock(return_value=fresh)
        cache = (
            AsyncMock(side_effect=cache_result)
            if isinstance(cache_result, Exception)
            else AsyncMock(return_value=cache_result)
        )
        connection = AsyncMock(return_value=transport)
        monkeypatch.setattr(shunt_module, "clear_cache", cache)
        monkeypatch.setattr(shunt_module, "establish_connection", connection)
        sub = ShuntBleClient().subscribe(
            resolve_device=lambda: device,
            rediscover_device=rediscover,
            on_update=MagicMock(),
            on_error=MagicMock(),
        )
        asyncio.create_task(sub.run())
        await asyncio.wait_for(transport.started.wait(), 1)
        await sub.close()
        cache.assert_awaited_once_with("A")
        assert connection.call_args.args[1] is (
            fresh if cache_result is True else original
        )
        assert rediscover.call_count == (1 if cache_result is True else 0)

    asyncio.run(scenario())


def test_subscription_defers_missing_device_and_rediscovery(monkeypatch):
    """Missing discovery/cooldown and missing refreshed handles cause no connect."""

    async def scenario():
        connection = AsyncMock()
        monkeypatch.setattr(shunt_module, "establish_connection", connection)
        monkeypatch.setattr(shunt_module, "clear_cache", AsyncMock(return_value=True))
        resolved = asyncio.Event()

        def resolve():
            resolved.set()
            return None

        sub = ShuntBleClient().subscribe(
            resolve_device=resolve, on_update=MagicMock(), on_error=MagicMock()
        )
        asyncio.create_task(sub.run())
        await asyncio.wait_for(resolved.wait(), 1)
        await sub.close()
        resolved.clear()

        def rediscover(_address):
            resolved.set()
            return None

        sub = ShuntBleClient().subscribe(
            resolve_device=_device,
            rediscover_device=rediscover,
            on_update=MagicMock(),
            on_error=MagicMock(),
        )
        asyncio.create_task(sub.run())
        await asyncio.wait_for(resolved.wait(), 1)
        await sub.close()
        connection.assert_not_awaited()

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["connect", "notify", "callback"])
def test_subscription_reports_errors_and_recovers(monkeypatch, failure):
    """Transport and consumer errors are visible, and the subscription can recover."""

    async def scenario():
        error = RuntimeError(failure)
        first = _Transport(notify_error=error if failure == "notify" else None)
        good = _Transport((_build_payload(), _build_payload()))
        connect = AsyncMock(
            side_effect=[error, good]
            if failure == "connect"
            else [first, good]
            if failure == "notify"
            else [good]
        )
        monkeypatch.setattr(shunt_module, "establish_connection", connect)
        monkeypatch.setattr(shunt_module, "clear_cache", AsyncMock(return_value=False))
        updates, errors = [], []

        def update(reading):
            if failure == "callback" and not errors:
                raise error
            updates.append(reading)

        sub = ShuntBleClient().subscribe(
            resolve_device=_device,
            on_update=update,
            on_error=errors.append,
            reconnect_delay=0,
        )
        asyncio.create_task(sub.run())
        await asyncio.wait_for(good.started.wait(), 1)
        await sub.close()
        assert errors == [error]
        assert len(updates) == (1 if failure == "callback" else 2)
        good.disconnect.assert_awaited_once()
        if failure == "notify":
            first.disconnect.assert_awaited_once()

    asyncio.run(scenario())


@pytest.mark.parametrize("phase", ["connect", "notify", "listening", "backoff"])
def test_subscription_cancellation_cleans_up(monkeypatch, phase):
    """Cancellation at each await propagates and releases any acquired transport."""

    async def scenario():
        entered = asyncio.Event()
        transport = _Transport()
        never = asyncio.Event()

        async def connect(*_args, **_kwargs):
            if phase == "connect":
                entered.set()
                await never.wait()
            if phase == "backoff":
                entered.set()
                raise RuntimeError("connect failed")
            return transport

        if phase == "notify":

            async def notify(*_args):
                entered.set()
                await never.wait()

            transport.start_notify = AsyncMock(side_effect=notify)
        elif phase == "listening":
            entered = transport.started
        monkeypatch.setattr(shunt_module, "establish_connection", connect)
        monkeypatch.setattr(shunt_module, "clear_cache", AsyncMock(return_value=False))
        sub = ShuntBleClient().subscribe(
            resolve_device=_device, on_update=MagicMock(), on_error=MagicMock()
        )
        task = asyncio.create_task(sub.run())
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        await asyncio.wait_for(sub.close(), 1)
        assert task.cancelled()
        assert transport.disconnect.await_count == (
            1 if phase in ("notify", "listening") else 0
        )

    asyncio.run(scenario())


def test_cleanup_is_bounded_and_reports_failure(monkeypatch):
    """Hanging stop_notify still attempts disconnect, and shutdown is bounded."""

    async def scenario():
        transport = _Transport()

        async def hang(*_args):
            await asyncio.Event().wait()

        transport.stop_notify = AsyncMock(side_effect=hang)
        transport.disconnect = AsyncMock(side_effect=hang)
        monkeypatch.setattr(
            shunt_module, "establish_connection", AsyncMock(return_value=transport)
        )
        monkeypatch.setattr(shunt_module, "clear_cache", AsyncMock(return_value=False))
        errors = []
        sub = ShuntBleClient(disconnect_timeout=0.01).subscribe(
            resolve_device=_device, on_update=MagicMock(), on_error=errors.append
        )
        asyncio.create_task(sub.run())
        await asyncio.wait_for(transport.started.wait(), 1)
        await asyncio.wait_for(sub.close(), 1)
        transport.stop_notify.assert_awaited_once()
        transport.disconnect.assert_awaited_once()
        assert len(errors) == 1
        assert isinstance(errors[0], TimeoutError)

    asyncio.run(scenario())


def test_cancel_intermittent_read_disconnects(monkeypatch):
    """Intermittent cancellation releases a subscribed transport too."""

    async def scenario():
        transport = _Transport()
        monkeypatch.setattr(
            shunt_module, "establish_connection", AsyncMock(return_value=transport)
        )
        task = asyncio.create_task(ShuntBleClient().read_device(_device()))
        await asyncio.wait_for(transport.started.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        transport.stop_notify.assert_awaited_once()
        transport.disconnect.assert_awaited_once()

    asyncio.run(scenario())


def test_subscription_ignores_disconnect_from_connector_retry(monkeypatch):
    """A failed internal connect attempt cannot terminate the successful retry."""

    async def scenario():
        transport = _Transport((_build_payload(),))

        async def connect(*_args, **kwargs):
            kwargs["disconnected_callback"](transport)
            return transport

        connection = AsyncMock(side_effect=connect)
        monkeypatch.setattr(shunt_module, "establish_connection", connection)
        monkeypatch.setattr(shunt_module, "clear_cache", AsyncMock(return_value=False))
        updates, errors = [], []
        sub = ShuntBleClient().subscribe(
            resolve_device=_device,
            on_update=updates.append,
            on_error=errors.append,
            reconnect_delay=0,
        )
        asyncio.create_task(sub.run())
        await asyncio.wait_for(transport.started.wait(), 1)
        await asyncio.sleep(0)
        assert len(updates) == 1
        assert errors == []
        transport.disconnect.assert_not_awaited()
        connection.assert_awaited_once()
        await sub.close()

    asyncio.run(scenario())


def test_cancelling_close_preserves_cleanup_and_propagates(monkeypatch):
    """An application shutdown deadline cancels close without losing disconnect."""

    async def scenario():
        transport = _Transport()
        cleanup_started, release_cleanup = asyncio.Event(), asyncio.Event()

        async def stop(*_args):
            cleanup_started.set()
            await release_cleanup.wait()

        transport.stop_notify = AsyncMock(side_effect=stop)
        transport.disconnect = AsyncMock(side_effect=RuntimeError("disconnect failed"))
        monkeypatch.setattr(
            shunt_module, "establish_connection", AsyncMock(return_value=transport)
        )
        monkeypatch.setattr(shunt_module, "clear_cache", AsyncMock(return_value=False))
        errors = []
        sub = ShuntBleClient().subscribe(
            resolve_device=_device, on_update=MagicMock(), on_error=errors.append
        )
        run_task = asyncio.create_task(sub.run())
        await asyncio.wait_for(transport.started.wait(), 1)
        close_task = asyncio.create_task(sub.close())
        await asyncio.wait_for(cleanup_started.wait(), 1)
        close_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await close_task
        # A second cancellation of the owned run task also cannot kill cleanup.
        run_task.cancel()
        release_cleanup.set()
        await asyncio.wait_for(sub.close(), 1)
        transport.disconnect.assert_awaited_once()
        assert len(errors) == 1
        assert str(errors[0]) == "disconnect failed"

    asyncio.run(scenario())


def test_intermittent_notify_failure_does_not_report_stale_success(monkeypatch):
    """A notification arriving before start_notify fails is not a successful read."""
    transport = _Transport(
        (_build_payload(),), notify_error=RuntimeError("notify failed")
    )
    monkeypatch.setattr(
        shunt_module, "establish_connection", AsyncMock(return_value=transport)
    )
    device = _device()
    device.parsed_data = {"shunt_voltage": 12.5}
    result = asyncio.run(ShuntBleClient().read_device(device))
    assert not result.success
    assert result.parsed_data == {"shunt_voltage": 12.5}
    assert str(result.error) == "notify failed"
