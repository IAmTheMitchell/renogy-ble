"""Renogy inverter BLE client and helpers."""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any

from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from renogy_ble.ble import (
    RENOGY_READ_CHAR_UUID,
    RENOGY_WRITE_CHAR_UUID,
    RenogyBLEDevice,
    RenogyBleReadResult,
    create_modbus_read_request,
)

logger = logging.getLogger(__name__)

INVERTER_DEVICE_ID = 0x20
INVERTER_INIT_CHAR_UUID = "0000ffd4-0000-1000-8000-00805f9b34fb"
INVERTER_COMMANDS: dict[str, tuple[int, int, int]] = {
    "main_data": (3, 4000, 32),
    "load_data": (3, 4408, 6),
    "device_id": (3, 4109, 1),
    "model": (3, 4311, 8),
}


class InverterBleClient:
    """BLE client for Renogy inverters."""

    def __init__(
        self,
        *,
        scanner: Any | None = None,
        device_id: int = INVERTER_DEVICE_ID,
        commands: dict[str, tuple[int, int, int]] | None = None,
        read_char_uuid: str = RENOGY_READ_CHAR_UUID,
        write_char_uuid: str = RENOGY_WRITE_CHAR_UUID,
        init_char_uuid: str = INVERTER_INIT_CHAR_UUID,
        max_notification_wait_time: float = 3.0,
        max_attempts: int = 3,
    ) -> None:
        self._scanner = scanner
        self._device_id = device_id
        self._commands = commands or INVERTER_COMMANDS
        self._read_char_uuid = read_char_uuid
        self._write_char_uuid = write_char_uuid
        self._init_char_uuid = init_char_uuid
        self._max_notification_wait_time = max_notification_wait_time
        self._max_attempts = max_attempts

    async def read_device(self, device: RenogyBLEDevice) -> RenogyBleReadResult:
        """Connect to an inverter, fetch data, and return parsed results."""
        device.parsed_data.clear()
        connection_kwargs = self._connection_kwargs()
        any_command_succeeded = False
        error: Exception | None = None

        try:
            client = await establish_connection(
                BleakClientWithServiceCache,
                device.ble_device,
                device.name or device.address,
                max_attempts=self._max_attempts,
                **connection_kwargs,
            )
        except (BleakError, asyncio.TimeoutError) as exc:
            logger.info(
                "Failed to establish connection with inverter %s: %s",
                device.name,
                exc,
            )
            return RenogyBleReadResult(False, dict(device.parsed_data), exc)

        notification_event = asyncio.Event()
        notification_data = bytearray()
        notification_started = False

        def notification_handler(_sender: object, data: bytearray) -> None:
            notification_data.extend(data)
            notification_event.set()

        try:
            try:
                init_data = await client.read_gatt_char(self._init_char_uuid)
                logger.debug(
                    "Read inverter init characteristic from %s: %s",
                    device.name,
                    bytes(init_data).hex(),
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "Skipping inverter init characteristic for %s: %s",
                    device.name,
                    exc,
                )

            await client.start_notify(self._read_char_uuid, notification_handler)
            notification_started = True

            for cmd_name, cmd in self._commands.items():
                notification_data.clear()
                notification_event.clear()

                modbus_request = create_modbus_read_request(self._device_id, *cmd)
                logger.debug(
                    "Sending inverter %s command: %s",
                    cmd_name,
                    list(modbus_request),
                )
                await client.write_gatt_char(self._write_char_uuid, modbus_request)

                word_count = cmd[2]
                expected_len = 3 + word_count * 2 + 2
                start_time = asyncio.get_running_loop().time()

                try:
                    while len(notification_data) < expected_len:
                        remaining = self._max_notification_wait_time - (
                            asyncio.get_running_loop().time() - start_time
                        )
                        if remaining <= 0:
                            raise asyncio.TimeoutError()
                        await asyncio.wait_for(notification_event.wait(), remaining)
                        notification_event.clear()
                except asyncio.TimeoutError:
                    logger.info(
                        "Timeout waiting for inverter %s (%s/%s bytes) from %s",
                        cmd_name,
                        len(notification_data),
                        expected_len,
                        device.name,
                    )
                    continue

                result_data = bytes(notification_data[:expected_len])
                cmd_success = device.update_parsed_data(
                    result_data, register=cmd[1], cmd_name=cmd_name
                )
                if cmd_success:
                    any_command_succeeded = True
                else:
                    logger.info(
                        "Failed to parse inverter %s response from %s",
                        cmd_name,
                        device.name,
                    )

            if not any_command_succeeded:
                error = RuntimeError("No inverter commands completed successfully")
        except BleakError as exc:
            logger.info("BLE error with inverter %s: %s", device.name, exc)
            error = exc
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("Error reading inverter %s: %s", device.name, exc)
            error = exc
        finally:
            if notification_started:
                try:
                    await client.stop_notify(self._read_char_uuid)
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "Error stopping notify for inverter %s: %s",
                        device.name,
                        exc,
                    )
                    if error is None:
                        error = exc
            if client.is_connected:
                try:
                    await client.disconnect()
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "Error disconnecting inverter %s: %s",
                        device.name,
                        exc,
                    )
                    if error is None:
                        error = exc

        return RenogyBleReadResult(
            any_command_succeeded, dict(device.parsed_data), error
        )

    def _connection_kwargs(self) -> dict[str, Any]:
        """Build connection kwargs for bleak-retry-connector."""
        if not self._scanner:
            return {}

        signature = inspect.signature(establish_connection)
        if "bleak_scanner" in signature.parameters:
            return {"bleak_scanner": self._scanner}
        if "scanner" in signature.parameters:
            return {"scanner": self._scanner}
        return {}
