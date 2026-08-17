"""Read-only Communication Hub battery discovery and polling."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from renogy_ble.battery import (
    BATTERY_VARIANT_LEGACY,
    HUB_BATTERY_PACK_STATUS_REGISTER,
    HUB_BATTERY_PACK_STATUS_WORD_COUNT,
    build_battery_command,
    parse_hub_battery_pack_status,
)
from renogy_ble.ble import (
    RenogyBLEDevice,
    RenogyBleClient,
    _PersistentBleSession,
)

logger = logging.getLogger(__name__)

HUB_BATTERY_SLAVE_IDS = tuple(range(0x30, 0x38))


@dataclass(frozen=True, slots=True)
class RenogyHubBattery:
    """Telemetry from one battery attached to a Renogy Communication Hub."""

    slave_id: int
    parsed_data: dict[str, Any]


@dataclass(slots=True)
class RenogyHubBatteryReadResult:
    """Result of a Communication Hub battery read."""

    success: bool
    batteries: list[RenogyHubBattery]
    error: Exception | None = None


class RenogyCommunicationHub:
    """Discover and read battery slaves over an existing Renogy BLE transport."""

    def __init__(
        self,
        client: RenogyBleClient,
        *,
        slave_ids: Iterable[int] = HUB_BATTERY_SLAVE_IDS,
        timeout: float | None = None,
    ) -> None:
        """Initialize the read-only Communication Hub helper."""
        normalized_slave_ids = tuple(dict.fromkeys(slave_ids))
        if any(slave_id < 1 or slave_id > 247 for slave_id in normalized_slave_ids):
            raise ValueError("Communication Hub slave IDs must be in the range 1-247")
        if timeout is not None and timeout <= 0:
            raise ValueError("Communication Hub timeout must be greater than zero")

        self._client = client
        self._slave_ids = normalized_slave_ids
        self._timeout = (
            client._max_notification_wait_time if timeout is None else timeout
        )
        self._discovered_slave_ids: dict[str, tuple[int, ...]] = {}

    def discovered_slave_ids(self, device: RenogyBLEDevice) -> tuple[int, ...]:
        """Return cached battery slave IDs for a BLE device."""
        return self._discovered_slave_ids.get(device.address, ())

    def clear_discovery_cache(self, device: RenogyBLEDevice | None = None) -> None:
        """Clear cached Hub slave IDs for one BLE device or all devices."""
        if device is None:
            self._discovered_slave_ids.clear()
            return
        self._discovered_slave_ids.pop(device.address, None)

    async def read_batteries(
        self,
        device: RenogyBLEDevice,
        *,
        rediscover: bool = False,
    ) -> RenogyHubBatteryReadResult:
        """Discover or poll Communication Hub batteries using one BLE session."""
        session = await self._client._prepare_session(device)
        batteries: list[RenogyHubBattery] = []
        error: Exception | None = None

        async with session.lock:
            try:
                await self._client._ensure_session_ready(device, session)
            except Exception as exc:  # noqa: BLE001
                await self._client._close_session(
                    device.address,
                    device.name,
                    session,
                    remove=True,
                )
                return RenogyHubBatteryReadResult(False, [], exc)

            cached_slave_ids = self._discovered_slave_ids.get(device.address)
            if rediscover or not cached_slave_ids:
                discovering = True
                target_slave_ids = self._slave_ids
            else:
                discovering = False
                target_slave_ids = cached_slave_ids
            probe_timed_out = False

            try:
                for slave_id in target_slave_ids:
                    if discovering:
                        response = await self._probe_battery_status(
                            session,
                            slave_id=slave_id,
                            device_name=device.name,
                        )
                        if response is None:
                            probe_timed_out = True
                            continue
                    else:
                        response = await self._read_battery_status(
                            session,
                            slave_id=slave_id,
                            device_name=device.name,
                        )
                        if response is None:
                            if session.desynchronized:
                                error = asyncio.TimeoutError(
                                    f"Timed out reading Hub battery 0x{slave_id:02X}"
                                )
                                break
                            continue

                    parsed = parse_hub_battery_pack_status(response)
                    if not parsed:
                        continue

                    batteries.append(
                        RenogyHubBattery(
                            slave_id=slave_id,
                            parsed_data=parsed,
                        )
                    )

                if discovering:
                    self._discovered_slave_ids[device.address] = tuple(
                        battery.slave_id for battery in batteries
                    )

                if not batteries and error is None:
                    error = RuntimeError("No Communication Hub batteries responded")
            except Exception as exc:  # noqa: BLE001
                error = exc

            if error is not None or session.desynchronized:
                await self._client._close_session(
                    device.address,
                    device.name,
                    session,
                    remove=True,
                )
            elif probe_timed_out:
                # Discovery intentionally tolerates missing slave IDs so the scan
                # can continue. Reconnect afterward to discard any late responses.
                await self._client._close_session(
                    device.address,
                    device.name,
                    session,
                    remove=False,
                )
            elif self._client._transport_mode != "persistent_session":
                await self._client._close_session(
                    device.address,
                    device.name,
                    session,
                    remove=False,
                )

        return RenogyHubBatteryReadResult(bool(batteries), batteries, error)

    async def _read_battery_status(
        self,
        session: _PersistentBleSession,
        *,
        slave_id: int,
        device_name: str,
    ) -> bytes | None:
        """Read one cached Hub battery using normal strict timeout semantics."""
        request = build_battery_command(
            BATTERY_VARIANT_LEGACY,
            HUB_BATTERY_PACK_STATUS_REGISTER,
            HUB_BATTERY_PACK_STATUS_WORD_COUNT,
            device_id=slave_id,
        )
        self._client._reset_notifications(session)
        if session.client is None:
            raise RuntimeError("BLE session is not connected")

        await session.client.write_gatt_char(
            session.write_target or self._client._write_char_uuid,
            request,
        )
        try:
            return await self._client._wait_for_valid_read_response(
                session,
                expected_device_id=slave_id,
                function_code=0x03,
                word_count=HUB_BATTERY_PACK_STATUS_WORD_COUNT,
                cmd_name=f"Hub battery 0x{slave_id:02X}",
                device_name=device_name,
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            return None

    async def _probe_battery_status(
        self,
        session: _PersistentBleSession,
        *,
        slave_id: int,
        device_name: str,
    ) -> bytes | None:
        """Probe one Hub slave without desynchronizing on an expected miss."""
        request = build_battery_command(
            BATTERY_VARIANT_LEGACY,
            HUB_BATTERY_PACK_STATUS_REGISTER,
            HUB_BATTERY_PACK_STATUS_WORD_COUNT,
            device_id=slave_id,
        )
        self._client._reset_notifications(session)
        if session.client is None:
            raise RuntimeError("BLE session is not connected")

        await session.client.write_gatt_char(
            session.write_target or self._client._write_char_uuid,
            request,
        )
        return await self._wait_for_probe_response(
            session,
            slave_id=slave_id,
            device_name=device_name,
        )

    async def _wait_for_probe_response(
        self,
        session: _PersistentBleSession,
        *,
        slave_id: int,
        device_name: str,
    ) -> bytes | None:
        """Wait for a slave-specific discovery response without flagging desync."""
        start_time = asyncio.get_running_loop().time()

        while True:
            response = self._client._extract_valid_read_response(
                session.notification_data,
                expected_device_id=slave_id,
                function_code=0x03,
                word_count=HUB_BATTERY_PACK_STATUS_WORD_COUNT,
            )
            if response is not None:
                return response

            remaining = self._timeout - (
                asyncio.get_running_loop().time() - start_time
            )
            if remaining <= 0:
                logger.debug(
                    "No Communication Hub battery response from slave 0x%02X on %s",
                    slave_id,
                    device_name,
                )
                return None

            try:
                await asyncio.wait_for(session.notification_event.wait(), remaining)
            except asyncio.TimeoutError:
                logger.debug(
                    "No Communication Hub battery response from slave 0x%02X on %s",
                    slave_id,
                    device_name,
                )
                return None
            session.notification_event.clear()
