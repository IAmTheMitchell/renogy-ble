"""BLE transport and Modbus framing for Renogy devices."""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal, Optional

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

# Default transport mode for request/response devices.
DEFAULT_TRANSPORT_MODE = "per_operation"

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
    device_id: int, register: int, value: int, function_code: int = 0x06
) -> bytearray:
    """Build a Modbus write single register frame.

    Args:
        device_id: Modbus device ID (1-247, or 0xFF for universal).
        register: Register address to write.
        value: 16-bit value to write.
        function_code: Modbus function code (typically 0x06 for write single register).

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


TransportMode = Literal["per_operation", "persistent_session"]


@dataclass(slots=True)
class _PersistentBleSession:
    """Track a persistent BLE connection for a single device."""

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    client: BleakClientWithServiceCache | None = None
    notification_event: asyncio.Event = field(default_factory=asyncio.Event)
    notification_data: bytearray = field(default_factory=bytearray)
    notify_started: bool = False


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
        transport_mode: TransportMode = DEFAULT_TRANSPORT_MODE,
    ) -> None:
        """Initialize the BLE client."""
        if transport_mode not in ("per_operation", "persistent_session"):
            raise ValueError(f"Unsupported transport mode: {transport_mode}")

        self._scanner = scanner
        self._device_id = device_id
        self._commands = commands or COMMANDS
        self._read_char_uuid = read_char_uuid
        self._write_char_uuid = write_char_uuid
        self._max_notification_wait_time = max_notification_wait_time
        self._max_attempts = max_attempts
        self._transport_mode = transport_mode
        self._persistent_sessions: dict[str, _PersistentBleSession] = {}
        self._persistent_sessions_guard = asyncio.Lock()

    async def read_device(self, device: RenogyBLEDevice) -> RenogyBleReadResult:
        """Connect to a device, fetch data, and return parsed results."""
        if device.device_type == "shunt300":
            try:
                from renogy_ble.shunt import ShuntBleClient
            except ImportError as exc:
                error = ValueError(
                    "Unsupported device type: shunt300 "
                    "(Smart Shunt client is unavailable)"
                )
                logger.error("%s", error)
                return RenogyBleReadResult(False, dict(device.parsed_data), exc)

            shunt_client = ShuntBleClient(
                max_notification_wait_time=self._max_notification_wait_time,
                max_attempts=self._max_attempts,
            )
            return await shunt_client.read_device(device)

        commands = self._commands.get(device.device_type)
        if not commands:
            error = ValueError(f"Unsupported device type: {device.device_type}")
            logger.error("%s", error)
            return RenogyBleReadResult(False, dict(device.parsed_data), error)

        session = await self._prepare_session(device)
        device.parsed_data.clear()
        async with session.lock:
            try:
                await self._ensure_session_ready(device, session)
            except Exception as connection_error:
                logger.info(
                    "Failed to prepare BLE session for device %s: %s",
                    device.name,
                    str(connection_error),
                )
                await self._close_session(
                    device.address,
                    device.name,
                    session,
                    remove=True,
                )
                return RenogyBleReadResult(
                    False, dict(device.parsed_data), connection_error
                )

            any_command_succeeded = False
            error: Exception | None = None

            try:
                logger.debug("Connected to device %s", device.name)

                for cmd_name, cmd in commands.items():
                    self._reset_notifications(session)

                    modbus_request = create_modbus_read_request(self._device_id, *cmd)
                    logger.debug(
                        "Sending %s command: %s",
                        cmd_name,
                        list(modbus_request),
                    )
                    if session.client is None:
                        raise RuntimeError("BLE session is not connected")
                    await session.client.write_gatt_char(
                        self._write_char_uuid,
                        modbus_request,
                    )

                    word_count = cmd[2]
                    expected_len = 3 + word_count * 2 + 2

                    try:
                        await self._wait_for_notification_bytes(
                            session,
                            expected_len,
                            cmd_name,
                            device.name,
                        )
                    except asyncio.TimeoutError:
                        continue

                    result_data = bytes(session.notification_data[:expected_len])
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

                if not any_command_succeeded:
                    error = RuntimeError("No commands completed successfully")
            except BleakError as exc:
                logger.info("BLE error with device %s: %s", device.name, str(exc))
                error = exc
            except Exception as exc:
                logger.error(
                    "Error reading data from device %s: %s", device.name, str(exc)
                )
                error = exc

            if error is not None:
                await self._close_session(
                    device.address,
                    device.name,
                    session,
                    remove=True,
                )
            elif self._transport_mode != "persistent_session":
                await self._close_session(
                    device.address,
                    device.name,
                    session,
                    remove=False,
                )

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
        session = await self._prepare_session(device)

        async with session.lock:
            try:
                await self._ensure_session_ready(device, session)
            except Exception as connection_error:
                logger.info(
                    "Failed to prepare BLE session for device %s: %s",
                    device.name,
                    str(connection_error),
                )
                await self._close_session(
                    device.address,
                    device.name,
                    session,
                    remove=True,
                )
                return RenogyBleWriteResult(False, connection_error)

            self._reset_notifications(session)
            modbus_request = create_modbus_write_request(
                self._device_id, register, value, function_code=function_code
            )
            logger.debug(
                "Sending write register command: %s",
                list(modbus_request),
            )
            try:
                if session.client is None:
                    raise RuntimeError("BLE session is not connected")
                await session.client.write_gatt_char(
                    self._write_char_uuid,
                    modbus_request,
                )
                await self._wait_for_write_response(
                    session,
                    register,
                    modbus_request,
                    function_code,
                )
            except asyncio.TimeoutError:
                await self._close_session(
                    device.address,
                    device.name,
                    session,
                    remove=True,
                )
                return RenogyBleWriteResult(False, asyncio.TimeoutError())
            except BleakError as exc:
                logger.info("BLE error with device %s: %s", device.name, str(exc))
                await self._close_session(
                    device.address,
                    device.name,
                    session,
                    remove=True,
                )
                return RenogyBleWriteResult(False, exc)
            except Exception as exc:
                logger.error(
                    "Error writing data to device %s: %s",
                    device.name,
                    str(exc),
                )
                await self._close_session(
                    device.address,
                    device.name,
                    session,
                    remove=True,
                )
                return RenogyBleWriteResult(False, exc)

            if self._transport_mode != "persistent_session":
                await self._close_session(
                    device.address,
                    device.name,
                    session,
                    remove=False,
                )

            return RenogyBleWriteResult(True, None)

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
        """Write a single register value to the device."""
        result = await self.write_single_register(device, register, value)
        if result.success:
            logger.info(
                "Successfully wrote value %s to register 0x%04X on device %s",
                value,
                register,
                device.name,
            )
        return result.success

    async def close_device(self, device: RenogyBLEDevice) -> None:
        """Close any persistent BLE session for the device."""
        session = await self._persistent_session_for(device.address)
        if session is None:
            return

        async with session.lock:
            await self._close_session(
                device.address,
                device.name,
                session,
                remove=True,
            )

    async def close(self) -> None:
        """Close all persistent BLE sessions owned by this client."""
        async with self._persistent_sessions_guard:
            sessions = list(self._persistent_sessions.items())

        for address, session in sessions:
            async with session.lock:
                await self._close_session(
                    address,
                    address,
                    session,
                    remove=True,
                )

    async def _prepare_session(self, device: RenogyBLEDevice) -> _PersistentBleSession:
        """Return the session to use for the next device transaction."""
        if self._transport_mode != "persistent_session":
            return _PersistentBleSession()

        async with self._persistent_sessions_guard:
            session = self._persistent_sessions.get(device.address)
            if session is None:
                session = _PersistentBleSession()
                self._persistent_sessions[device.address] = session
            return session

    async def _persistent_session_for(
        self, address: str
    ) -> _PersistentBleSession | None:
        """Look up a stored persistent session by BLE address."""
        async with self._persistent_sessions_guard:
            return self._persistent_sessions.get(address)

    async def _ensure_session_ready(
        self,
        device: RenogyBLEDevice,
        session: _PersistentBleSession,
    ) -> None:
        """Ensure the BLE connection and notifications are ready for use."""
        if session.client is None or not session.client.is_connected:
            connection_kwargs = self._connection_kwargs()
            session.client = await establish_connection(
                BleakClientWithServiceCache,
                device.ble_device,
                device.name or device.address,
                max_attempts=self._max_attempts,
                **connection_kwargs,
            )
            session.notify_started = False
            self._reset_notifications(session)

        if session.notify_started:
            return

        def notification_handler(_sender, data):
            session.notification_data.extend(data)
            session.notification_event.set()

        await session.client.start_notify(self._read_char_uuid, notification_handler)
        session.notify_started = True

    async def _close_session(
        self,
        device_address: str,
        device_name: str,
        session: _PersistentBleSession,
        *,
        remove: bool,
    ) -> None:
        """Stop notifications and disconnect a session."""
        if session.client is not None:
            if session.notify_started:
                try:
                    await session.client.stop_notify(self._read_char_uuid)
                except Exception as exc:
                    logger.debug(
                        "Error stopping notify for device %s: %s",
                        device_name,
                        str(exc),
                    )

            if session.client.is_connected:
                try:
                    await session.client.disconnect()
                    logger.debug("Disconnected from device %s", device_name)
                except Exception as exc:
                    logger.debug(
                        "Error disconnecting from device %s: %s",
                        device_name,
                        str(exc),
                    )

        session.client = None
        session.notify_started = False
        self._reset_notifications(session)

        if remove:
            async with self._persistent_sessions_guard:
                self._persistent_sessions.pop(device_address, None)

    def _reset_notifications(self, session: _PersistentBleSession) -> None:
        """Clear buffered notification bytes before the next request."""
        session.notification_data.clear()
        session.notification_event.clear()

    async def _wait_for_notification_bytes(
        self,
        session: _PersistentBleSession,
        expected_len: int,
        cmd_name: str,
        device_name: str,
    ) -> None:
        """Wait until enough notification bytes arrive for a read response."""
        start_time = asyncio.get_running_loop().time()

        while len(session.notification_data) < expected_len:
            remaining = self._max_notification_wait_time - (
                asyncio.get_running_loop().time() - start_time
            )
            if remaining <= 0:
                logger.info(
                    "Timeout – only %s / %s bytes received for %s from device %s",
                    len(session.notification_data),
                    expected_len,
                    cmd_name,
                    device_name,
                )
                raise asyncio.TimeoutError()
            await asyncio.wait_for(session.notification_event.wait(), remaining)
            session.notification_event.clear()

    async def _wait_for_write_response(
        self,
        session: _PersistentBleSession,
        register: int,
        request: bytes | bytearray,
        function_code: int,
    ) -> None:
        """Wait for and validate a Modbus write response."""
        expected_len = 8
        exception_len = 5
        exception_code_mask = function_code | 0x80
        start_time = asyncio.get_running_loop().time()

        while True:
            remaining = self._max_notification_wait_time - (
                asyncio.get_running_loop().time() - start_time
            )
            if remaining <= 0:
                logger.info(
                    "Timeout – only %s / %s bytes received for write register %s",
                    len(session.notification_data),
                    expected_len,
                    register,
                )
                raise asyncio.TimeoutError()
            await asyncio.wait_for(session.notification_event.wait(), remaining)
            session.notification_event.clear()

            if (
                len(session.notification_data) >= exception_len
                and session.notification_data[0] == self._device_id
                and session.notification_data[1] == exception_code_mask
            ):
                exception_response = bytes(session.notification_data[:exception_len])
                crc_low, crc_high = modbus_crc(exception_response[:3])
                if exception_response[3:5] != bytes([crc_low, crc_high]):
                    logger.info(
                        "Write exception CRC mismatch for register %s",
                        register,
                    )
                    raise RuntimeError("Exception CRC mismatch")

                exception_code = exception_response[2]
                logger.info(
                    "Write exception response for register %s: code %s",
                    register,
                    exception_code,
                )
                raise RuntimeError(
                    f"Modbus exception code {exception_code} for register {register}"
                )

            if len(session.notification_data) < expected_len:
                continue

            response = bytes(session.notification_data[:expected_len])
            if response[:6] != request[:6]:
                logger.info(
                    "Write response mismatch for register %s. Expected %s got %s",
                    register,
                    list(request[:6]),
                    list(response[:6]),
                )
                raise RuntimeError("Response mismatch")

            crc_low, crc_high = modbus_crc(response[:6])
            if response[6:8] != bytes([crc_low, crc_high]):
                logger.info(
                    "Write response CRC mismatch for register %s",
                    register,
                )
                raise RuntimeError("CRC mismatch")

            return
