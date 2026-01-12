"""BLE transport and Modbus framing for Renogy devices."""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from renogy_ble.renogy_parser import RenogyParser

logger = logging.getLogger(__name__)

# BLE Characteristics and Service UUIDs
RENOGY_READ_CHAR_UUID = "0000fff1-0000-1000-8000-00805f9b34fb"
RENOGY_WRITE_CHAR_UUID = "0000ffd1-0000-1000-8000-00805f9b34fb"

# Time in minutes to wait before attempting to reconnect to unavailable devices
UNAVAILABLE_RETRY_INTERVAL = 10

# Maximum time to wait for a notification response (seconds)
MAX_NOTIFICATION_WAIT_TIME = 2.0

# Default device ID for Renogy devices
DEFAULT_DEVICE_ID = 0xFF

# Default device type
DEFAULT_DEVICE_TYPE = "controller"

# Controller register for DC load control
LOAD_CONTROL_REGISTER = 0x010A

# Modbus commands for requesting data
# Format: (function_code, start_register, word_count)
COMMANDS = {
    DEFAULT_DEVICE_TYPE: {
        "device_info": (3, 12, 8),
        "device_id": (3, 26, 1),
        "battery": (3, 57348, 1),
        "pv": (3, 256, 34),
    },
    "dcc": {
        "device_info": (3, 12, 8),
        "device_id": (3, 26, 1),
        "dynamic_data": (3, 256, 32),  # 0x0100-0x011F (32 words)
        "status": (3, 288, 8),  # 0x0120-0x0127 (8 words)
        "current_limit": (3, 57345, 1),  # 0xE001 (1 word) - max charging current
        "parameters": (3, 57347, 18),  # 0xE003-0xE014 (18 words)
        "reverse_charging_voltage": (3, 57376, 1),  # 0xE020 (1 word)
        "solar_cutoff_current": (3, 57400, 1),  # 0xE038 (1 word)
    },
}


def modbus_crc(data: bytes | bytearray) -> tuple[int, int]:
    """Calculate the Modbus CRC16 of the given data.

    Returns a tuple (crc_low, crc_high) where the low byte is sent first.
    """
    crc = 0xFFFF
    for pos in data:
        crc ^= pos
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    crc_low = crc & 0xFF
    crc_high = (crc >> 8) & 0xFF
    return (crc_low, crc_high)


def create_modbus_read_request(
    device_id: int, function_code: int, register: int, word_count: int
) -> bytearray:
    """Build a Modbus read request frame."""
    frame = bytearray(
        [
            device_id,
            function_code,
            (register >> 8) & 0xFF,
            register & 0xFF,
            (word_count >> 8) & 0xFF,
            word_count & 0xFF,
        ]
    )
    crc_low, crc_high = modbus_crc(frame)
    frame.extend([crc_low, crc_high])
    logger.debug("create_request_payload: %s (%s)", register, list(frame))
    return frame


def create_modbus_write_request(
    device_id: int, function_code: int, register: int, value: int
) -> bytearray:
    """Build a Modbus write single register frame.

    Args:
        device_id: Modbus device ID (1-247, or 0xFF for universal).
        function_code: Modbus function code (typically 0x06 for write single register).
        register: Register address to write.
        value: 16-bit value to write.

    Returns:
        Complete Modbus frame with CRC.
    """
    frame = bytearray(
        [
            device_id,
            function_code,
            (register >> 8) & 0xFF,
            register & 0xFF,
            (value >> 8) & 0xFF,
            value & 0xFF,
        ]
    )
    crc_low, crc_high = modbus_crc(frame)
    frame.extend([crc_low, crc_high])
    logger.debug(
        "create_write_request: register=0x%04X value=%s frame=%s",
        register,
        value,
        list(frame),
    )
    return frame


def clean_device_name(name: str | None) -> str:
    """Clean the device name by removing unwanted characters."""
    if name:
        cleaned_name = name.strip()
        cleaned_name = re.sub(r"\s+", " ", cleaned_name).strip()
        return cleaned_name
    return ""


class RenogyBLEDevice:
    """Representation of a Renogy BLE device."""

    def __init__(
        self,
        ble_device: BLEDevice,
        advertisement_rssi: Optional[int] = None,
        device_type: str = DEFAULT_DEVICE_TYPE,
    ):
        """Initialize the Renogy BLE device."""
        self.ble_device = ble_device
        self.address = ble_device.address

        cleaned_name = clean_device_name(ble_device.name)
        self.name = cleaned_name or "Unknown Renogy Device"

        # Use the provided advertisement RSSI if available, otherwise set to None.
        self.rssi = advertisement_rssi
        self.last_seen = datetime.now()
        self.data: Optional[dict[str, Any]] = None
        self.failure_count = 0
        self.max_failures = 3
        self.available = True
        self.parsed_data: dict[str, Any] = {}
        self.device_type = device_type
        self.last_unavailable_time: Optional[datetime] = None

    @property
    def is_available(self) -> bool:
        """Return True if device is available."""
        return self.available and self.failure_count < self.max_failures

    @property
    def should_retry_connection(self) -> bool:
        """Check if we should retry connecting to an unavailable device."""
        if self.is_available:
            return True

        if self.last_unavailable_time is None:
            self.last_unavailable_time = datetime.now()
            return False

        retry_time = self.last_unavailable_time + timedelta(
            minutes=UNAVAILABLE_RETRY_INTERVAL
        )
        if datetime.now() >= retry_time:
            logger.debug(
                "Retry interval reached for unavailable device %s. "
                "Attempting reconnection...",
                self.name,
            )
            self.last_unavailable_time = datetime.now()
            return True

        return False

    def update_availability(self, success: bool, error: Optional[Exception] = None):
        """Update the availability based on success/failure of communication."""
        if success:
            if self.failure_count > 0:
                logger.info(
                    "Device %s communication restored after %s consecutive failures",
                    self.name,
                    self.failure_count,
                )
            self.failure_count = 0
            if not self.available:
                logger.info("Device %s is now available", self.name)
                self.available = True
                self.last_unavailable_time = None
        else:
            self.failure_count += 1
            error_msg = f" Error message: {str(error)}" if error else ""
            logger.info(
                "Communication failure with Renogy device: %s. "
                "(Consecutive polling failure #%s. "
                "Device will be marked unavailable after %s failures.)%s",
                self.name,
                self.failure_count,
                self.max_failures,
                error_msg,
            )

            if self.failure_count >= self.max_failures and self.available:
                error_msg = f". Error message: {str(error)}" if error else ""
                logger.error(
                    "Renogy device %s marked unavailable after %s "
                    "consecutive polling failures%s",
                    self.name,
                    self.max_failures,
                    error_msg,
                )
                self.available = False
                self.last_unavailable_time = datetime.now()

    def update_parsed_data(
        self, raw_data: bytes, register: int, cmd_name: str = "unknown"
    ) -> bool:
        """Parse the raw data using the renogy-ble parser."""
        if not raw_data:
            logger.error(
                "Attempted to parse empty data from device %s for command %s.",
                self.name,
                cmd_name,
            )
            return False

        try:
            if len(raw_data) < 5:
                logger.warning(
                    "Response too short for %s: %s bytes. Raw data: %s",
                    cmd_name,
                    len(raw_data),
                    raw_data.hex(),
                )
                return False

            byte_count = raw_data[2]
            expected_len = 3 + byte_count + 2
            if len(raw_data) < expected_len:
                logger.warning(
                    "Got only %s / %s bytes for %s (register %s). Raw: %s",
                    len(raw_data),
                    expected_len,
                    cmd_name,
                    register,
                    raw_data.hex(),
                )
                return False
            function_code = raw_data[1] if len(raw_data) > 1 else 0
            if function_code & 0x80:
                error_code = raw_data[2] if len(raw_data) > 2 else 0
                logger.error(
                    "Modbus error in %s response: function code %s, error code %s",
                    cmd_name,
                    function_code,
                    error_code,
                )
                return False

            parsed = RenogyParser.parse(raw_data, self.device_type, register)

            if not parsed:
                logger.warning(
                    "No data parsed from %s response (register %s). Length: %s",
                    cmd_name,
                    register,
                    len(raw_data),
                )
                return False

            self.parsed_data.update(parsed)

            logger.debug(
                "Successfully parsed %s data from device %s: %s",
                cmd_name,
                self.name,
                parsed,
            )
            return True

        except Exception as exc:
            logger.error(
                "Error parsing %s data from device %s: %s",
                cmd_name,
                self.name,
                str(exc),
            )
            logger.debug(
                "Raw data for %s (register %s): %s, Length: %s",
                cmd_name,
                register,
                raw_data.hex() if raw_data else "None",
                len(raw_data) if raw_data else 0,
            )
            return False


@dataclass(slots=True)
class RenogyBleReadResult:
    """Result of a BLE read operation."""

    success: bool
    parsed_data: dict[str, Any]
    error: Exception | None = None


@dataclass(slots=True)
class RenogyBleWriteResult:
    """Result of a BLE write operation."""

    success: bool
    error: Exception | None = None


class RenogyBleClient:
    """Handle BLE connection and Modbus I/O for Renogy devices."""

    def __init__(
        self,
        *,
        scanner: Any | None = None,
        device_id: int = DEFAULT_DEVICE_ID,
        commands: dict[str, dict[str, tuple[int, int, int]]] | None = None,
        read_char_uuid: str = RENOGY_READ_CHAR_UUID,
        write_char_uuid: str = RENOGY_WRITE_CHAR_UUID,
        max_notification_wait_time: float = MAX_NOTIFICATION_WAIT_TIME,
        max_attempts: int = 3,
    ) -> None:
        """Initialize the BLE client."""
        self._scanner = scanner
        self._device_id = device_id
        self._commands = commands or COMMANDS
        self._read_char_uuid = read_char_uuid
        self._write_char_uuid = write_char_uuid
        self._max_notification_wait_time = max_notification_wait_time
        self._max_attempts = max_attempts

    async def read_device(self, device: RenogyBLEDevice) -> RenogyBleReadResult:
        """Connect to a device, fetch data, and return parsed results."""
        commands = self._commands.get(device.device_type)
        if not commands:
            error = ValueError(f"Unsupported device type: {device.device_type}")
            logger.error("%s", error)
            return RenogyBleReadResult(False, dict(device.parsed_data), error)

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
        except (BleakError, asyncio.TimeoutError) as connection_error:
            logger.info(
                "Failed to establish connection with device %s: %s",
                device.name,
                str(connection_error),
            )
            return RenogyBleReadResult(
                False, dict(device.parsed_data), connection_error
            )

        try:
            logger.debug("Connected to device %s", device.name)
            notification_event = asyncio.Event()
            notification_data = bytearray()

            def notification_handler(_sender, data):
                notification_data.extend(data)
                notification_event.set()

            await client.start_notify(self._read_char_uuid, notification_handler)

            for cmd_name, cmd in commands.items():
                notification_data.clear()
                notification_event.clear()

                modbus_request = create_modbus_read_request(self._device_id, *cmd)
                logger.debug(
                    "Sending %s command: %s",
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
                        "Timeout – only %s / %s bytes received for %s from device %s",
                        len(notification_data),
                        expected_len,
                        cmd_name,
                        device.name,
                    )
                    continue

                result_data = bytes(notification_data[:expected_len])
                logger.debug(
                    "Received %s data length: %s (expected %s)",
                    cmd_name,
                    len(result_data),
                    expected_len,
                )

                cmd_success = device.update_parsed_data(
                    result_data, register=cmd[1], cmd_name=cmd_name
                )

                if cmd_success:
                    logger.debug(
                        "Successfully read and parsed %s data from device %s",
                        cmd_name,
                        device.name,
                    )
                    any_command_succeeded = True
                else:
                    logger.info(
                        "Failed to parse %s data from device %s",
                        cmd_name,
                        device.name,
                    )

            await client.stop_notify(self._read_char_uuid)
            if not any_command_succeeded:
                error = RuntimeError("No commands completed successfully")
        except BleakError as exc:
            logger.info("BLE error with device %s: %s", device.name, str(exc))
            error = exc
        except Exception as exc:
            logger.error("Error reading data from device %s: %s", device.name, str(exc))
            error = exc
        finally:
            if client.is_connected:
                try:
                    await client.disconnect()
                    logger.debug("Disconnected from device %s", device.name)
                except Exception as exc:
                    logger.debug(
                        "Error disconnecting from device %s: %s",
                        device.name,
                        str(exc),
                    )
                    if error is None:
                        error = exc

        return RenogyBleReadResult(
            any_command_succeeded, dict(device.parsed_data), error
        )

    async def write_single_register(
        self,
        device: RenogyBLEDevice,
        register: int,
        value: int,
        function_code: int = 0x06,
    ) -> RenogyBleWriteResult:
        """Write a single register value and return success."""
        connection_kwargs = self._connection_kwargs()

        try:
            client = await establish_connection(
                BleakClientWithServiceCache,
                device.ble_device,
                device.name or device.address,
                max_attempts=self._max_attempts,
                **connection_kwargs,
            )
        except (BleakError, asyncio.TimeoutError) as connection_error:
            logger.info(
                "Failed to establish connection with device %s: %s",
                device.name,
                str(connection_error),
            )
            return RenogyBleWriteResult(False, connection_error)

        notification_event = asyncio.Event()
        notification_data = bytearray()
        notification_started = False

        def notification_handler(_sender, data):
            notification_data.extend(data)
            notification_event.set()

        try:
            await client.start_notify(self._read_char_uuid, notification_handler)
            notification_started = True

            modbus_request = create_modbus_write_request(
                self._device_id, function_code, register, value
            )
            logger.debug(
                "Sending write register command: %s",
                list(modbus_request),
            )
            await client.write_gatt_char(self._write_char_uuid, modbus_request)

            expected_len = 8
            exception_len = 5
            exception_code_mask = function_code | 0x80
            start_time = asyncio.get_running_loop().time()

            try:
                while True:
                    remaining = self._max_notification_wait_time - (
                        asyncio.get_running_loop().time() - start_time
                    )
                    if remaining <= 0:
                        raise asyncio.TimeoutError()
                    await asyncio.wait_for(notification_event.wait(), remaining)
                    notification_event.clear()

                    if (
                        len(notification_data) >= exception_len
                        and notification_data[0] == self._device_id
                        and notification_data[1] == exception_code_mask
                    ):
                        exception_response = bytes(notification_data[:exception_len])
                        crc_low, crc_high = modbus_crc(exception_response[:3])
                        if exception_response[3:5] != bytes([crc_low, crc_high]):
                            logger.info(
                                "Write exception CRC mismatch for register %s",
                                register,
                            )
                            return RenogyBleWriteResult(
                                False, RuntimeError("Exception CRC mismatch")
                            )

                        exception_code = exception_response[2]
                        logger.info(
                            "Write exception response for register %s: code %s",
                            register,
                            exception_code,
                        )
                        return RenogyBleWriteResult(
                            False,
                            RuntimeError(
                                f"Modbus exception code {exception_code} for register {register}"
                            ),
                        )

                    if len(notification_data) >= expected_len:
                        break
            except asyncio.TimeoutError:
                logger.info(
                    "Timeout – only %s / %s bytes received for write register %s",
                    len(notification_data),
                    expected_len,
                    register,
                )
                return RenogyBleWriteResult(False, asyncio.TimeoutError())

            response = bytes(notification_data[:expected_len])
            if response[:6] != modbus_request[:6]:
                logger.info(
                    "Write response mismatch for register %s. Expected %s got %s",
                    register,
                    list(modbus_request[:6]),
                    list(response[:6]),
                )
                return RenogyBleWriteResult(False, RuntimeError("Response mismatch"))

            crc_low, crc_high = modbus_crc(response[:6])
            if response[6:8] != bytes([crc_low, crc_high]):
                logger.info(
                    "Write response CRC mismatch for register %s",
                    register,
                )
                return RenogyBleWriteResult(False, RuntimeError("CRC mismatch"))

            return RenogyBleWriteResult(True, None)

        except BleakError as exc:
            logger.info("BLE error with device %s: %s", device.name, str(exc))
            return RenogyBleWriteResult(False, exc)
        except Exception as exc:
            logger.error(
                "Error writing data to device %s: %s",
                device.name,
                str(exc),
            )
            return RenogyBleWriteResult(False, exc)
        finally:
            if notification_started:
                try:
                    await client.stop_notify(self._read_char_uuid)
                except Exception as exc:
                    logger.debug(
                        "Error stopping notify for device %s: %s",
                        device.name,
                        str(exc),
                    )
            if client.is_connected:
                try:
                    await client.disconnect()
                    logger.debug("Disconnected from device %s", device.name)
                except Exception as exc:
                    logger.debug(
                        "Error disconnecting from device %s: %s",
                        device.name,
                        str(exc),
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

    async def write_register(
        self, device: RenogyBLEDevice, register: int, value: int
    ) -> bool:
        """Write a single register value to the device.

        Args:
            device: The target device
            register: Register address to write (e.g., 0xE004 for battery type)
            value: 16-bit value to write

        Returns:
            True if write was successful, False otherwise
        """
        connection_kwargs = self._connection_kwargs()

        try:
            client = await establish_connection(
                BleakClientWithServiceCache,
                device.ble_device,
                device.name or device.address,
                max_attempts=self._max_attempts,
                **connection_kwargs,
            )
        except (BleakError, asyncio.TimeoutError) as connection_error:
            logger.error(
                "Failed to connect for write to device %s: %s",
                device.name,
                str(connection_error),
            )
            return False

        try:
            logger.debug("Connected to device %s for write", device.name)
            notification_event = asyncio.Event()
            notification_data = bytearray()

            def notification_handler(_sender, data):
                notification_data.extend(data)
                notification_event.set()

            await client.start_notify(self._read_char_uuid, notification_handler)

            # Build and send the write request
            modbus_request = create_modbus_write_request(
                self._device_id, 0x06, register, value
            )
            logger.debug(
                "Sending write command to register 0x%04X: %s",
                register,
                list(modbus_request),
            )
            await client.write_gatt_char(self._write_char_uuid, modbus_request)

            # Wait for response (function 06 echoes the request on success)
            expected_len = 8  # Same length as request
            try:
                await asyncio.wait_for(
                    notification_event.wait(), self._max_notification_wait_time
                )
            except asyncio.TimeoutError:
                logger.error(
                    "Timeout waiting for write response from device %s",
                    device.name,
                )
                await client.stop_notify(self._read_char_uuid)
                return False

            await client.stop_notify(self._read_char_uuid)

            # Verify response
            if len(notification_data) < expected_len:
                logger.error(
                    "Write response too short: got %s bytes, expected %s",
                    len(notification_data),
                    expected_len,
                )
                return False

            # Check for error response (function code with high bit set)
            if notification_data[1] & 0x80:
                error_code = notification_data[2] if len(notification_data) > 2 else 0
                logger.error(
                    "Modbus write error: function code 0x%02X, error code %s",
                    notification_data[1],
                    error_code,
                )
                return False

            # Verify the echoed register and value match
            resp_register = (notification_data[2] << 8) | notification_data[3]
            resp_value = (notification_data[4] << 8) | notification_data[5]

            if resp_register != register or resp_value != value:
                logger.error(
                    "Write response mismatch: expected reg=0x%04X val=%s, "
                    "got reg=0x%04X val=%s",
                    register,
                    value,
                    resp_register,
                    resp_value,
                )
                return False

            logger.info(
                "Successfully wrote value %s to register 0x%04X on device %s",
                value,
                register,
                device.name,
            )
            return True

        except BleakError as exc:
            logger.error(
                "BLE error during write to device %s: %s", device.name, str(exc)
            )
            return False
        except Exception as exc:
            logger.error("Error writing to device %s: %s", device.name, str(exc))
            return False
        finally:
            if client.is_connected:
                try:
                    await client.disconnect()
                except Exception as exc:
                    logger.debug(
                        "Error disconnecting from device %s: %s",
                        device.name,
                        str(exc),
                    )
