"""
Parser for Renogy BLE device data

This module provides functionality to parse raw byte data from Renogy BLE devices
according to the register mappings defined in register_map.py
"""

import logging

from renogy_ble.register_map import REGISTER_MAP

# Set up logger for this module
logger = logging.getLogger(__name__)


def parse_value(
    data, offset, length, byte_order, scale=None, bit_offset=None, data_type="int"
):
    """
    Parse a value from raw byte data at the specified offset and length.

    Args:
        data (bytes): The raw byte data to parse
        offset (int): The starting offset in the data
        length (int): The length of data to parse in bytes
        byte_order (str): The byte order ('big' or 'little')
        scale (float, optional): Scale factor to apply to the value
        bit_offset (int, optional): Bit offset for boolean or bit flag values
        data_type (str, optional): The type of data to parse; 'int' (default) or 'string'

    Returns:
        int, float, or str: The parsed value
    """
    # Check if we have enough data
    if offset + length > len(data):
        raise ValueError(
            f"Data length ({len(data)}) is not sufficient to read {length} bytes at offset {offset}"
        )

    # Extract the bytes at the specified offset and length
    value_bytes = data[offset : offset + length]

    if data_type == "string":
        try:
            # Decode as ASCII and strip any whitespace or null bytes
            return value_bytes.decode("ascii", errors="ignore").strip("\x00").strip()
        except Exception as e:
            raise ValueError(f"Error decoding string: {e}")
    else:
        # Convert bytes to integer using the specified byte order
        value = int.from_bytes(value_bytes, byteorder=byte_order)

        # Handle bit offset if specified (for boolean fields)
        if bit_offset is not None:
            value = (value >> bit_offset) & 1

        # Apply scaling if specified
        if scale is not None:
            value = value * scale

        return value


class RenogyBaseParser:
    """
    Base parser for Renogy BLE devices.

    This class handles the general parsing logic for any Renogy device model,
    using the register mappings defined in register_map.py.
    """

    def __init__(self):
        """Initialize the parser with the register map."""
        self.register_map = REGISTER_MAP

    def parse(self, data, model, register):
        """
        Parse raw byte data for the specified device model and register.

        Args:
            data (bytes): The raw byte data received from the device
            model (str): The device model (e.g., "rover")
            register (int): The register number to parse

        Returns:
            dict: A dictionary containing the parsed values for fields belonging to the specified register
        """
        result = {}

        # Check if the model exists in our register map
        if model not in self.register_map:
            logger.warning("Unsupported model: %s", model)
            return result

        model_map = self.register_map[model]

        # Iterate through each field in the model map that belongs to the specified register
        for field_name, field_info in model_map.items():
            if field_info.get("register") != register:
                continue

            offset = field_info["offset"]
            length = field_info["length"]
            byte_order = field_info["byte_order"]
            scale = field_info.get("scale")
            bit_offset = field_info.get("bit_offset")
            data_type = field_info.get("data_type", "int")

            try:
                value = parse_value(
                    data, offset, length, byte_order, scale, bit_offset, data_type
                )

                # Apply mapping if it exists
                if "map" in field_info and value in field_info["map"]:
                    value = field_info["map"][value]

                result[field_name] = value

            except ValueError as e:
                logger.warning(
                    "Unexpected data length, partial parsing attempted. Expected at least %d bytes for field '%s' at offset %d, but data length is only %d bytes. Error: %s",
                    offset + length,
                    field_name,
                    offset,
                    len(data),
                    str(e),
                )
                continue

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

    def parse_data(self, data, register=None):
        """
        Parse raw data from a Rover device.

        Args:
            data (bytes): The raw byte data received from the device
            register (int, optional): The register number to parse. If not provided,
                                      returns an empty dictionary.
        Returns:
            dict: A dictionary containing the parsed values specific to the Rover model
        """
        # Need register to be provided now
        if register is None:
            logger.warning("Register parameter is required but not provided")
            return {}

        # Use the base parser's parse method with the rover model
        return self.parse(data, self.model, register)
