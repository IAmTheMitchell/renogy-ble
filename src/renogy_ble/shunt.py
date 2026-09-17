"""Smart Shunt BLE payload parsing and read client."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import clear_cache, establish_connection

from renogy_ble.ble import RenogyBLEDevice, RenogyBleReadResult

logger = logging.getLogger(__name__)

# Smart Shunt notification characteristic.
SHUNT_NOTIFY_CHAR_UUID = "0000c411-0000-1000-8000-00805f9b34fb"

# Smart Shunt payload size from empirical captures.
SHUNT_EXPECTED_PAYLOAD_LENGTH = 110
SHUNT_LIVE_HEADER = bytes.fromhex("42570119")
SHUNT_FRAMED_PREFIX = bytes.fromhex("61d2")
SHUNT_FRAMED_PREFIX_LENGTH = 4
SHUNT_REQUIRED_FIELD_LENGTH = 28

KEY_SHUNT_VOLTAGE = "shunt_voltage"
KEY_SHUNT_CURRENT = "shunt_current"
KEY_SHUNT_POWER = "shunt_power"
KEY_SHUNT_SOC = "shunt_soc"
KEY_SHUNT_ENERGY_CHARGED_TOTAL = "energy_charged_total"
KEY_SHUNT_ENERGY_DISCHARGED_TOTAL = "energy_discharged_total"
KEY_SHUNT_DECODE_CONFIDENCE = "decode_confidence"
KEY_SHUNT_READING_VERIFIED = "reading_verified"


def _bytes_to_number(
    payload: bytes,
    offset: int,
    length: int,
    *,
    signed: bool = False,
    scale: float = 1.0,
    decimals: int | None = None,
) -> float | int | None:
    """Extract a numeric value from a payload slice."""
    if len(payload) < offset + length:
        return None

    value = int.from_bytes(
        payload[offset : offset + length], byteorder="big", signed=signed
    )
    scaled = value * scale
    return round(scaled, decimals) if decimals is not None else scaled


def parse_shunt_payload(payload: bytes) -> dict[str, Any] | None:
    """Parse a raw Smart Shunt notification frame."""
    if len(payload) < SHUNT_REQUIRED_FIELD_LENGTH:
        return None
    if not payload.startswith(SHUNT_LIVE_HEADER):
        return None

    voltage = _bytes_to_number(payload, 25, 3, scale=0.001, decimals=2)
    starter_voltage = _bytes_to_number(payload, 30, 2, scale=0.001, decimals=2)
    current = _bytes_to_number(payload, 21, 3, signed=True, scale=0.001, decimals=2)
    power = (
        round(voltage * current, 2)
        if voltage is not None and current is not None
        else None
    )
    soc = _bytes_to_number(payload, 34, 2, scale=0.1, decimals=1)
    battery_temp = _bytes_to_number(payload, 66, 2, scale=0.1, decimals=1)

    if voltage is None or current is None or power is None:
        return None
    if voltage < 6 or voltage > 80:
        return None
    if abs(current) > 500:
        return None
    if abs(power) > 10000:
        return None
    if battery_temp is not None and (battery_temp < -40 or battery_temp > 100):
        battery_temp = None
    if soc is not None and (soc < 0 or soc > 200):
        soc = None

    return {
        KEY_SHUNT_VOLTAGE: voltage,
        KEY_SHUNT_CURRENT: current,
        KEY_SHUNT_POWER: power,
        KEY_SHUNT_SOC: soc,
        KEY_SHUNT_ENERGY_CHARGED_TOTAL: None,
        KEY_SHUNT_ENERGY_DISCHARGED_TOTAL: None,
        KEY_SHUNT_DECODE_CONFIDENCE: "live_header",
        KEY_SHUNT_READING_VERIFIED: True,
        "starter_battery_voltage": starter_voltage,
        "battery_temperature": battery_temp,
    }


class ShuntNotificationDecoder:
    """Decode one device's byte stream and integrate its energy totals.

    Feed arbitrary notification fragments in arrival order. Each returned mapping
    is a complete normalized reading, including raw diagnostics. Reset the buffer
    at each connection boundary; energy totals survive resets. Use one decoder per
    device and a monotonic clock (seconds). No checksum is known for this format;
    the live header and existing field plausibility checks determine validity.
    """

    def __init__(
        self,
        *,
        expected_length: int = SHUNT_EXPECTED_PAYLOAD_LENGTH,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if expected_length < SHUNT_REQUIRED_FIELD_LENGTH:
            raise ValueError("expected_length must include the required fields")
        self._expected_length = expected_length
        self._clock = clock
        self._buffer = bytearray()
        self._last_ts: float | None = None
        self._charged_wh = 0.0
        self._discharged_wh = 0.0

    def reset_buffer(self) -> None:
        """Discard partial bytes without resetting the device's energy totals."""
        self._buffer.clear()

    def feed(self, data: bytes | bytearray) -> list[dict[str, Any]]:
        """Consume bytes, returning all complete live readings in stream order."""
        self._buffer.extend(data)
        readings = []
        while True:
            offset = self._buffer.find(SHUNT_LIVE_HEADER)
            if offset < 0:
                # Retain enough bytes for a header split across notifications.
                del self._buffer[: -(len(SHUNT_LIVE_HEADER) - 1)]
                break
            del self._buffer[:offset]
            if len(self._buffer) < self._expected_length:
                break
            raw = bytes(self._buffer[: self._expected_length])
            parsed = parse_shunt_payload(raw)
            if parsed is None:
                del self._buffer[0]
                continue
            del self._buffer[: self._expected_length]
            now = self._clock()
            if self._last_ts is not None:
                dt_hours = (now - self._last_ts) / 3600
                if 0 < dt_hours < 10:
                    energy_wh = float(parsed[KEY_SHUNT_POWER]) * dt_hours
                    self._charged_wh += max(energy_wh, 0)
                    self._discharged_wh += max(-energy_wh, 0)
            self._last_ts = now
            parsed[KEY_SHUNT_ENERGY_CHARGED_TOTAL] = round(self._charged_wh / 1000, 3)
            parsed[KEY_SHUNT_ENERGY_DISCHARGED_TOTAL] = round(
                self._discharged_wh / 1000, 3
            )
            parsed["raw_payload"] = raw.hex()
            parsed["raw_words"] = [
                int.from_bytes(raw[i : i + 2], "big") for i in range(0, len(raw) - 1, 2)
            ]
            readings.append(parsed)
        return readings


async def _disconnect_client(
    client: BleakClient, notify_char_uuid: str, timeout: float
) -> Exception | None:
    """Bound notification cleanup and always attempt to release the connection."""
    error = None
    try:
        if client.is_connected:
            await asyncio.wait_for(client.stop_notify(notify_char_uuid), timeout)
    except Exception as exc:
        error = exc
    finally:
        try:
            await asyncio.wait_for(client.disconnect(), timeout)
        except Exception as exc:
            error = exc
    return error


class ShuntBleClient:
    """Read or subscribe to Smart Shunt data with per-device decoder state.

    Do not run multiple reads/subscriptions for the same address concurrently.
    The caller owns subscription tasks and must await ``close()`` on shutdown.
    """

    def __init__(
        self,
        *,
        notify_char_uuid: str = SHUNT_NOTIFY_CHAR_UUID,
        expected_length: int = SHUNT_EXPECTED_PAYLOAD_LENGTH,
        max_notification_wait_time: float = 3.0,
        max_attempts: int = 3,
        disconnect_timeout: float = 5.0,
    ) -> None:
        self._notify_char_uuid = notify_char_uuid
        self._expected_length = expected_length
        self._max_notification_wait_time = max_notification_wait_time
        self._max_attempts = max_attempts
        self._disconnect_timeout = disconnect_timeout
        self._decoders: dict[str, ShuntNotificationDecoder] = {}

    def _decoder(self, address: str) -> ShuntNotificationDecoder:
        if address not in self._decoders:
            self._decoders[address] = ShuntNotificationDecoder(
                expected_length=self._expected_length
            )
        return self._decoders[address]

    def subscribe(
        self,
        *,
        resolve_device: Callable[[], RenogyBLEDevice | None],
        on_update: Callable[[dict[str, Any]], None],
        on_error: Callable[[Exception], None],
        rediscover_device: Callable[[str], BLEDevice | None] | None = None,
        reconnect_delay: float = 10.0,
    ) -> ShuntSubscription:
        """Create a subscription; run its ``run()`` coroutine in the caller's task.

        ``resolve_device`` is called before each connection attempt. Returning None
        defers connection (for discovery or a caller's retry cooldown). After a
        successful BlueZ cache clear, ``rediscover_device`` supplies a fresh handle;
        without it, BleakScanner performs discovery. Callbacks run synchronously on
        the event loop and must not block. Errors include connection, notification,
        unexpected disconnect, callback and cleanup failures. Retrying is automatic.
        """
        return ShuntSubscription(
            self,
            resolve_device=resolve_device,
            on_update=on_update,
            on_error=on_error,
            rediscover_device=rediscover_device,
            reconnect_delay=reconnect_delay,
        )

    async def read_device(self, device: RenogyBLEDevice) -> RenogyBleReadResult:
        """Connect, decode the first complete live reading, then disconnect."""
        decoder = self._decoder(device.address)
        decoder.reset_buffer()
        event = asyncio.Event()
        parsed_result: dict[str, Any] | None = None
        error: Exception | None = None
        client: BleakClient | None = None
        received = 0
        accepting = True
        success = False

        def notification_handler(
            _sender: BleakGATTCharacteristic | int | str, data: bytearray
        ) -> None:
            nonlocal parsed_result, received
            if not accepting or parsed_result is not None:
                return
            received += len(data)
            readings = decoder.feed(data)
            if readings:
                parsed_result = readings[0]
                event.set()

        try:
            client = await establish_connection(
                BleakClient,
                device.ble_device,
                device.name or device.address,
                max_attempts=self._max_attempts,
                use_services_cache=False,
            )
            await client.start_notify(self._notify_char_uuid, notification_handler)
            try:
                await asyncio.wait_for(event.wait(), self._max_notification_wait_time)
            except TimeoutError:
                error = RuntimeError(
                    f"Empty shunt payload parsed (received {received} bytes in "
                    f"{self._max_notification_wait_time}s)"
                )
            if parsed_result is not None:
                device.parsed_data = parsed_result
                success = True
        except Exception as exc:
            error = exc
        finally:
            accepting = False
            decoder.reset_buffer()
            if client is not None:
                cleanup_error = await _disconnect_client(
                    client, self._notify_char_uuid, self._disconnect_timeout
                )
                if error is None:
                    error = cleanup_error
        return RenogyBleReadResult(success, dict(device.parsed_data), error)


class ShuntSubscription:
    """A sustained, reconnecting Shunt session created by ShuntBleClient.subscribe.

    Run once, in an application-owned task. Cancellation propagates after bounded
    cleanup. ``close()`` is idempotent and waits for connection cleanup, including
    when the application already cancelled the task. A closed subscription cannot
    be restarted; create another using the same client to retain energy totals.
    """

    def __init__(
        self,
        owner: ShuntBleClient,
        *,
        resolve_device: Callable[[], RenogyBLEDevice | None],
        on_update: Callable[[dict[str, Any]], None],
        on_error: Callable[[Exception], None],
        rediscover_device: Callable[[str], BLEDevice | None] | None,
        reconnect_delay: float,
    ) -> None:
        if reconnect_delay < 0:
            raise ValueError("reconnect_delay must be non-negative")
        self._owner = owner
        self._resolve_device = resolve_device
        self._on_update = on_update
        self._on_error = on_error
        self._rediscover_device = rediscover_device
        self._reconnect_delay = reconnect_delay
        self._closed = False
        self._task: asyncio.Task[Any] | None = None
        self._cleanup_task: asyncio.Task[None] | None = None

    def _report_error(self, error: Exception) -> None:
        try:
            self._on_error(error)
        except Exception:
            logger.exception("Smart Shunt error callback failed")

    async def close(self) -> None:
        """Stop reconnecting and await the running session's bounded cleanup."""
        self._closed = True
        task = self._task
        if task is not None and task is not asyncio.current_task():
            if not task.cancelling():
                task.cancel()
            # A cancelled run task is expected; cancellation of close itself must
            # still propagate without interrupting the transport's cleanup task.
            await asyncio.shield(asyncio.gather(task, return_exceptions=True))
        if self._cleanup_task is not None:
            await asyncio.shield(self._cleanup_task)

    async def run(self) -> None:
        """Maintain the subscription until closed or cancelled by the caller."""
        if self._closed or self._task is not None:
            raise RuntimeError("Subscription already started or closed")
        self._task = asyncio.current_task()
        try:
            while not self._closed:
                try:
                    device = self._resolve_device()
                    if device is not None:
                        await self._session(device)
                except Exception as exc:
                    self._report_error(exc)
                if not self._closed:
                    await asyncio.sleep(self._reconnect_delay)
        finally:
            self._closed = True
            self._task = None

    async def _session(self, device: RenogyBLEDevice) -> None:
        owner = self._owner
        decoder = owner._decoder(device.address)
        decoder.reset_buffer()
        try:
            cache_cleared = await clear_cache(device.address)
        except Exception:
            # Cache clearing is unavailable on some backends; still try connecting.
            logger.debug("Smart Shunt cache clear failed", exc_info=True)
            cache_cleared = False
        if cache_cleared:
            if self._rediscover_device is None:
                refreshed = await BleakScanner.find_device_by_address(device.address)
            else:
                refreshed = self._rediscover_device(device.address)
            if refreshed is None:
                return
            device.ble_device = refreshed

        disconnected = asyncio.Event()
        client: BleakClient | None = None
        accepting = True

        def notification_handler(
            _sender: BleakGATTCharacteristic | int | str, data: bytearray
        ) -> None:
            if not accepting or self._closed:
                return
            try:
                readings = decoder.feed(data)
            except Exception as exc:
                self._report_error(exc)
                return
            for reading in readings:
                try:
                    self._on_update(reading)
                except Exception as exc:
                    self._report_error(exc)

        try:
            client = await establish_connection(
                BleakClient,
                device.ble_device,
                device.name or device.address,
                max_attempts=owner._max_attempts,
                use_services_cache=False,
                disconnected_callback=lambda _client: disconnected.set(),
            )
            # The connector reuses its callback while retrying. Disconnects from
            # failed attempts must not end the successfully established session.
            disconnected.clear()
            await client.start_notify(owner._notify_char_uuid, notification_handler)
            while (
                not self._closed and client.is_connected and not disconnected.is_set()
            ):
                try:
                    await asyncio.wait_for(disconnected.wait(), 5.0)
                except TimeoutError:
                    pass
            if not self._closed:
                raise BleakError(f"Smart Shunt {device.address} disconnected")
        finally:
            accepting = False
            decoder.reset_buffer()
            if client is not None:
                self._cleanup_task = asyncio.create_task(self._cleanup(client))
                await asyncio.shield(self._cleanup_task)
                self._cleanup_task = None

    async def _cleanup(self, client: BleakClient) -> None:
        """Report cleanup errors even when the run task was cancelled again."""
        error = await _disconnect_client(
            client, self._owner._notify_char_uuid, self._owner._disconnect_timeout
        )
        if error is not None:
            self._report_error(error)
