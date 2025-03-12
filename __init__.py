"""
Renogy BLE Parser Package

This package provides functionality to parse data from Renogy BLE devices.
It supports different device models by routing the parsing to model-specific parsers.
"""

import logging
from parser import RoverParser

from register_map import REGISTER_MAP

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
    based on the specified model.
    """

    @staticmethod
    def parse(raw_data, model):
        """
        Parse raw BLE data for the specified Renogy device model.

        Args:
            raw_data (bytes): Raw byte data received from the device
            model (str): The device model (e.g., "rover")

        Returns:
            dict: A dictionary containing the parsed values or an empty dictionary
                 if the model is not supported
        """
        # Check if the model is supported in the register map
        if model not in REGISTER_MAP:
            logger.warning("Unsupported model: %s", model)
            return {}

        # Route to the appropriate model-specific parser
        if model == "rover":
            parser = RoverParser()
            return parser.parse_data(raw_data)

        # This should not be reached if the model checking is comprehensive,
        # but included as a safeguard
        logger.warning(
            "Model %s is in REGISTER_MAP but no parser is implemented", model
        )
        return {}
