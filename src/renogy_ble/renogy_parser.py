"""Entry point for parsing Renogy BLE device data."""

from __future__ import annotations

import logging

from renogy_ble.parser import ControllerParser
from renogy_ble.register_map import REGISTER_MAP

logger = logging.getLogger(__name__)


class RenogyParser:
    """Entry point for parsing Renogy BLE device data."""

    @staticmethod
    def parse(raw_data: bytes, device_type: str, register: int) -> dict:
        """Parse raw BLE data for the specified Renogy device type and register."""
        if device_type not in REGISTER_MAP:
            logger.warning("Unsupported type: %s", device_type)
            return {}

        if device_type == "controller":
            parser = ControllerParser()
            return parser.parse_data(raw_data, register)

        logger.warning(
            "Type %s is in REGISTER_MAP but no parser is implemented", device_type
        )
        return {}
