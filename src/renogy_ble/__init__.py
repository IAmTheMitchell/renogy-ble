"""
Renogy BLE Parser Package

This package provides functionality to parse data from Renogy BLE devices.
It supports different device models by routing the parsing to type-specific parsers.
"""

import logging

from renogy_ble.parser import ControllerParser
from renogy_ble.register_map import REGISTER_MAP

# Set up logging
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


class RenogyParser:
    """
    Entry point for parsing Renogy BLE device data.

    This class provides a static method to parse raw data from Renogy devices
    based on the specified type and register.
    """

    @staticmethod
    def parse(raw_data, type, register):
        """
        Parse raw BLE data for the specified Renogy device type and register.

        Args:
            raw_data (bytes): Raw byte data received from the device
            type (str): The device type (e.g., "controller" or "battery")
            register (int): The register number to parse

        Returns:
            dict: A dictionary containing the parsed values or an empty dictionary
                 if the model is not supported
        """
        # Check if the model is supported in the register map
        if type not in REGISTER_MAP:
            logger.warning("Unsupported type: %s", type)
            return {}

        # Route to the appropriate model-specific parser
        if type == "controller":
            parser = ControllerParser()
            return parser.parse_data(raw_data, register)

        # This should not be reached if the model checking is comprehensive,
        # but included as a safeguard
        logger.warning("Type %s is in REGISTER_MAP but no parser is implemented", type)
        return {}
