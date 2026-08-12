"""
Parser for Renogy BLE device data

This module provides functionality to parse raw byte data from Renogy BLE devices
according to the register mappings defined in register_map.py
"""

import logging
from typing import Literal

from renogy_ble.register_map import REGISTER_MAP, FieldInfo, RegisterMap

# Set up logger for this module
logger = logging.getLogger(__name__)

_RegisterFields = dict[str, dict[int, tuple[tuple[str, FieldInfo], ...]]]


def _index_register_fields(register_map: RegisterMap) -> _RegisterFields:
    """Group parser fields by model and command start register."""
    indexed_fields: _RegisterFields = {}
    for model, model_map in register_map.items():
        fields_by_register: dict[int, list[tuple[str, FieldInfo]]] = {}
        for field_name, field_info in model_map.items():
            register = field_info.get("register")
            if register is not None:
                fields_by_register.setdefault(register, []).append(
                    (field_name, field_info)
                )
        indexed_fields[model] = {
            register: tuple(fields) for register, fields in fields_by_register.items()
        }
    return indexed_fields


def parse_value(
    data: bytes,
    offset: int,
    length: int,
    byte_order: Literal["big", "little"],
    scale: float | None = None,
    bit_offset: int | None = None,
    data_type: Literal["int", "string"] = "int",
    signed: bool = False,
    signed_encoding: Literal["twos_complement", "sign_magnitude"] = "twos_complement",
) -> int | float | str:
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
        signed_encoding (str, optional): Signed encoding for 1-byte values. Supports
            'twos_complement' (default) or 'sign_magnitude'.

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

        if signed and data_type == "int" and length == 1:
            raw_byte = value_bytes[0]
            if signed_encoding == "sign_magnitude":
                if raw_byte & 0x80:
                    value = -(raw_byte & 0x7F)
                else:
                    value = raw_byte

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

    def __init__(self) -> None:
        """Initialize the parser with the register map."""
        self.register_map: RegisterMap = REGISTER_MAP
        self._fields_by_register = _index_register_fields(self.register_map)

    def parse(
        self, data: bytes, model: str, register: int
    ) -> dict[str, int | float | str]:
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
        result: dict[str, int | float | str] = {}

        fields_by_register = self._fields_by_register.get(model)
        if fields_by_register is None:
            logger.warning("Unsupported model: %s", model)
            return result

        for field_name, field_info in fields_by_register.get(register, ()):
            offset = field_info["offset"]
            length = field_info["length"]
            byte_order = field_info["byte_order"]
            scale = field_info.get("scale")
            bit_offset = field_info.get("bit_offset")
            data_type = field_info.get("data_type", "int")
            signed = field_info.get("signed", False)
            signed_encoding = field_info.get("signed_encoding", "twos_complement")

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
                    signed_encoding=signed_encoding,
                )

                value_map = field_info.get("map")
                if (
                    value_map is not None
                    and isinstance(value, int)
                    and value in value_map
                ):
                    value = value_map[value]

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


class RenogyDeviceParser(RenogyBaseParser):
    """Parse register data for one configured Renogy device type."""

    device_type: str

    @property
    def type(self) -> str:
        """Return the device type using the legacy public attribute name."""
        return self.device_type

    @type.setter
    def type(self, value: str) -> None:
        """Update the device type using the legacy public attribute name."""
        self.device_type = value

    def parse_data(
        self, data: bytes, register: int | None = None
    ) -> dict[str, int | float | str]:
        """Parse raw data for this parser's device type and start register."""
        if register is None:
            logger.warning("Register parameter is required but not provided")
            return {}

        return self.parse(data, self.device_type, register)


class ControllerParser(RenogyDeviceParser):
    """
    Parser specifically for Renogy charge controllers.

    This class extends the RenogyBaseParser to provide any controller-specific parsing
    functionality that may be needed.
    """

    device_type = "controller"


class DCCParser(RenogyDeviceParser):
    """
    Parser specifically for Renogy DC-DC chargers.

    This class extends the RenogyBaseParser to parse data from DCC devices
    like DCC30S, DCC50S, RBC20D1U, RBC40D1U, etc.
    """

    device_type = "dcc"
