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
    data,
    offset,
    length,
    byte_order,
    scale=None,
    bit_offset=None,
    data_type="int",
    signed=False,
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
        data_type (str, optional): The type of data to parse; 'int' (default) or
            'string'
        signed (bool, optional): Whether to interpret integer values as signed.

    Returns:
        int, float, or str: The parsed value
    """
    # Check if we have enough data
    if offset + length > len(data):
        raise ValueError(
            (
                f"Data length ({len(data)}) is not sufficient to read {length} bytes"
                f" at offset {offset}"
            )
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
        value = int.from_bytes(value_bytes, byteorder=byte_order, signed=signed)

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
            dict: A dictionary containing the parsed values for fields belonging to
                the specified register
        """
        result = {}

        # Check if the model exists in our register map
        if model not in self.register_map:
            logger.warning("Unsupported model: %s", model)
            return result

        model_map = self.register_map[model]

        # Iterate through fields in the model map that belong to the given register.
        for field_name, field_info in model_map.items():
            if field_info.get("register") != register:
                continue

            offset = field_info["offset"]
            length = field_info["length"]
            byte_order = field_info["byte_order"]
            scale = field_info.get("scale")
            bit_offset = field_info.get("bit_offset")
            data_type = field_info.get("data_type", "int")
            signed = field_info.get("signed", False)

            try:
                value = parse_value(
                    data,
                    offset,
                    length,
                    byte_order,
                    scale=scale,
                    bit_offset=bit_offset,
                    data_type=data_type,
                    signed=signed,
                )

                # Apply mapping if it exists
                if "map" in field_info and value in field_info["map"]:
                    value = field_info["map"][value]

                result[field_name] = value

            except ValueError as e:
                logger.warning(
                    (
                        "Unexpected data length, partial parsing attempted. Expected"
                        " at least %d bytes for field '%s' at offset %d, but data"
                        " length is only %d bytes. Error: %s"
                    ),
                    offset + length,
                    field_name,
                    offset,
                    len(data),
                    str(e),
                )
                continue

        return result


class ControllerParser(RenogyBaseParser):
    """
    Parser specifically for Renogy charge controllers.

    This class extends the RenogyBaseParser to provide any controller-specific parsing
    functionality that may be needed.
    """

    def __init__(self):
        """Initialize the controller parser."""
        super().__init__()
        self.type = "controller"

    def parse_data(self, data, register=None):
        """
        Parse raw data from a controller device.

        Args:
            data (bytes): The raw byte data received from the device
            register (int, optional): The register number to parse. If not provided,
                                      returns an empty dictionary.
        Returns:
            dict: A dictionary containing the parsed values specific to the device type
        """
        if register is None:
            logger.warning("Register parameter is required but not provided")
            return {}

        # Use the base parser's parse method with the device type
        return self.parse(data, self.type, register)
