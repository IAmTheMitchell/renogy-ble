"""
Parser for Renogy BLE device data

This module provides functionality to parse raw byte data from Renogy BLE devices
according to the register mappings defined in register_map.py
"""

import logging

from renogy_ble.register_map import REGISTER_MAP

# Set up logger for this module
logger = logging.getLogger(__name__)


def parse_value(data, offset, length, byte_order):
    """
    Parse a value from raw byte data at the specified offset and length.

    Args:
        data (bytes): The raw byte data to parse
        offset (int): The starting offset in the data
        length (int): The length of data to parse in bytes
        byte_order (str): The byte order ('big' or 'little')

    Returns:
        int: The parsed integer value
    """
    # Check if we have enough data
    if offset + length > len(data):
        raise ValueError(
            f"Data length ({len(data)}) is not sufficient to read {length} bytes at offset {offset}"
        )

    # Extract the bytes at the specified offset and length
    value_bytes = data[offset : offset + length]

    # Convert bytes to integer using the specified byte order
    return int.from_bytes(value_bytes, byteorder=byte_order)


class RenogyBaseParser:
    """
    Base parser for Renogy BLE devices.

    This class handles the general parsing logic for any Renogy device model,
    using the register mappings defined in register_map.py.
    """

    def __init__(self):
        """Initialize the parser with the register map."""
        self.register_map = REGISTER_MAP

    def parse(self, data, model):
        """
        Parse raw byte data for the specified device model.

        Args:
            data (bytes): The raw byte data received from the device
            model (str): The device model (e.g., "rover")

        Returns:
            dict: A dictionary containing the parsed values
        """
        result = {}

        # Check if the model exists in our register map
        if model not in self.register_map:
            logger.warning("Unsupported model: %s", model)
            return result

        # Get the register map for this model
        model_map = self.register_map[model]

        # Log data characteristics for debugging
        logger.debug(
            "Parsing %d bytes for model %s with %d fields",
            len(data),
            model,
            len(model_map),
        )

        # Iterate through each field in the model map
        for field_name, field_info in model_map.items():
            register = field_info["register"]
            length = field_info["length"]
            byte_order = field_info["byte_order"]

            # Calculate the offset in the data based on the register address
            offset = register - 256  # Assuming register 256 maps to offset 0

            try:
                # Parse the value
                value = parse_value(data, offset, length, byte_order)

                # Apply mapping if it exists
                if "map" in field_info and value in field_info["map"]:
                    value = field_info["map"][value]

                result[field_name] = value

            except ValueError:
                # If there's not enough data, log a warning and continue
                logger.warning(
                    "Unexpected data length, partial parsing attempted. "
                    "Expected at least %d bytes for field '%s' at offset %d, "
                    "but data length is only %d bytes.",
                    offset + length,
                    field_name,
                    offset,
                    len(data),
                )

                # We can't parse any more fields if we've run out of data
                break

        return result


class RoverParser(RenogyBaseParser):
    """
    Parser specifically for Renogy Rover charge controllers.

    This class extends the RenogyBaseParser to provide any Rover-specific parsing
    functionality that may be needed.
    """

    def __init__(self):
        """Initialize the Rover parser."""
        super().__init__()
        self.model = "rover"

    def parse_data(self, data):
        """
        Parse raw data from a Rover device.

        Args:
            data (bytes): The raw byte data received from the device

        Returns:
            dict: A dictionary containing the parsed values specific to the Rover model
        """
        # Use the base parser's parse method with the rover model
        return self.parse(data, self.model)