"""Smart Shunt BLE payload parsing and read client."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from renogy_ble.ble import RenogyBLEDevice, RenogyBleReadResult

logger = logging.getLogger(__name__)

# Smart Shunt notification characteristic.
SHUNT_NOTIFY_CHAR_UUID = "0000c411-0000-1000-8000-00805f9b34fb"

# Smart Shunt payload size from empirical captures.
SHUNT_EXPECTED_PAYLOAD_LENGTH = 110

KEY_SHUNT_VOLTAGE = "shunt_voltage"
KEY_SHUNT_CURRENT = "shunt_current"
KEY_SHUNT_POWER = "shunt_power"
KEY_SHUNT_SOC = "shunt_soc"
KEY_SHUNT_ENERGY = "shunt_energy"


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
    if voltage < 0 or voltage > 80:
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
        KEY_SHUNT_ENERGY: None,
        "starter_battery_voltage": starter_voltage,
        "battery_temperature": battery_temp,
    }


class ShuntBleClient:
    """BLE client for Smart Shunt notification reads."""

    def __init__(
        self,
        *,
        notify_char_uuid: str = SHUNT_NOTIFY_CHAR_UUID,
        expected_length: int = SHUNT_EXPECTED_PAYLOAD_LENGTH,
        max_notification_wait_time: float = 3.0,
        max_attempts: int = 3,
    ) -> None:
        self._notify_char_uuid = notify_char_uuid
        self._expected_length = expected_length
        self._max_notification_wait_time = max_notification_wait_time
        self._max_attempts = max_attempts
        self._energy_state: dict[str, tuple[float, float]] = {}

    def _integrate_energy(
        self, *, device_address: str, power_w: float | int | None, now_ts: float
    ) -> float:
        """Integrate power over time and return net energy in kWh for one device."""
        state = self._energy_state.get(device_address)
        if state is None:
            self._energy_state[device_address] = (now_ts, 0.0)
            return 0.0

        last_ts, net_wh = state
        dt_hours = (now_ts - last_ts) / 3600
        if 0 < dt_hours < 10 and power_w is not None:
            net_wh += float(power_w) * dt_hours

        self._energy_state[device_address] = (now_ts, net_wh)
        return net_wh / 1000

    async def read_device(self, device: RenogyBLEDevice) -> RenogyBleReadResult:
        """Connect, wait for one notification payload, parse, and return result."""
        payload = bytearray()
        event = asyncio.Event()
        error: Exception | None = None
        success = False

        try:
            client = await establish_connection(
                BleakClientWithServiceCache,
                device.ble_device,
                device.name or device.address,
                max_attempts=self._max_attempts,
            )
        except (BleakError, asyncio.TimeoutError) as exc:
            logger.info("Failed to connect to Smart Shunt %s: %s", device.address, exc)
            return RenogyBleReadResult(False, dict(device.parsed_data), exc)

        try:

            def notification_handler(
                _sender: BleakGATTCharacteristic | int | str, data: bytearray
            ) -> None:
                payload.extend(data)
                event.set()

            await client.start_notify(self._notify_char_uuid, notification_handler)
            loop = asyncio.get_running_loop()
            start = loop.time()

            while len(payload) < self._expected_length:
                remaining = self._max_notification_wait_time - (loop.time() - start)
                if remaining <= 0:
                    raise asyncio.TimeoutError(
                        f"No shunt payload after {self._max_notification_wait_time}s"
                    )
                await asyncio.wait_for(event.wait(), remaining)
                event.clear()

            raw_payload = bytes(payload[: self._expected_length])
            parsed = parse_shunt_payload(raw_payload)

            if parsed:
                now = loop.time()
                net_kwh = self._integrate_energy(
                    device_address=device.address,
                    power_w=parsed.get(KEY_SHUNT_POWER),
                    now_ts=now,
                )
                parsed[KEY_SHUNT_ENERGY] = round(net_kwh, 3)

                parsed["raw_payload"] = raw_payload.hex()
                parsed["raw_words"] = [
                    int.from_bytes(
                        raw_payload[i * 2 : (i + 1) * 2], "big", signed=False
                    )
                    for i in range(len(raw_payload) // 2)
                ]
                device.parsed_data = parsed
                success = True
            else:
                error = RuntimeError("Empty shunt payload parsed")

            await client.stop_notify(self._notify_char_uuid)
        except asyncio.TimeoutError as exc:
            error = exc
        except asyncio.CancelledError:
            raise
        except (BleakError, Exception) as exc:  # noqa: BLE001
            error = exc
        finally:
            if client.is_connected:
                try:
                    await client.disconnect()
                except Exception as exc:  # noqa: BLE001
                    if error is None:
                        error = exc

        return RenogyBleReadResult(success, dict(device.parsed_data), error)
