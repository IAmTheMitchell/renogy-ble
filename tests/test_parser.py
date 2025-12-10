"""
Unit tests for the Renogy BLE parser implementation.

This module tests the functionality of the parser module to ensure it correctly
parses raw byte data according to the register mapping definitions.
"""

import io
import logging
from unittest.mock import patch

import pytest

# Import the modules to be tested
from renogy_ble.parser import ControllerParser, RenogyBaseParser, parse_value


def test_parse_value_big_endian():
    """Test parsing a value with big-endian byte order."""
    data = bytes([0x01, 0x02, 0x03, 0x04, 0x05])

    # Test parsing 2 bytes from offset 1 with big-endian byte order
    value = parse_value(data, 1, 2, "big")
    assert value == 0x0203


def test_parse_value_little_endian():
    """Test parsing a value with little-endian byte order."""
    data = bytes([0x01, 0x02, 0x03, 0x04, 0x05])

    # Test parsing 2 bytes from offset 2 with little-endian byte order
    value = parse_value(data, 2, 2, "little")
    assert value == 0x0403


def test_parse_value_signed_byte():
    """Test parsing a signed byte value."""
    data = bytes([0xFF, 0x7F])

    assert parse_value(data, 0, 1, "big", signed=True) == -1
    assert parse_value(data, 1, 1, "big", signed=True) == 127


def test_parse_value_insufficient_data():
    """Test parsing a value with insufficient data."""
    data = bytes([0x01, 0x02, 0x03])

    # Test parsing 2 bytes from offset 2, which only has 1 byte available
    with pytest.raises(ValueError):
        parse_value(data, 2, 2, "big")


@pytest.fixture
def base_parser():
    """Fixture that returns a RenogyBaseParser instance."""
    return RenogyBaseParser()


def test_parse_unsupported_model(base_parser):
    """Test parsing data with an unsupported model."""
    # Create some dummy data
    data = bytes([0x01, 0x02, 0x03, 0x04])

    with patch("renogy_ble.parser.logger") as mock_logger:
        # Parse with an unsupported model
        result = base_parser.parse(data, "unsupported_model", 256)

        # Check that the result is an empty dictionary
        assert result == {}

        # Check that a warning was logged
        mock_logger.warning.assert_called_with(
            "Unsupported model: %s", "unsupported_model"
        )


def test_parse_full_data():
    """Test parsing full data for a supported model."""
    # Create a mock parser with a controlled register map
    test_register_map = {
        "test_model": {
            "test_field": {
                "register": 256,
                "length": 2,
                "byte_order": "big",
                "offset": 0,
            },
            "test_field_with_map": {
                "register": 256,
                "length": 1,
                "byte_order": "big",
                "map": {1: "on", 0: "off"},
                "offset": 2,
            },
        }
    }

    with patch("renogy_ble.parser.REGISTER_MAP", test_register_map):
        parser = RenogyBaseParser()

        # Create test data with values that should produce predictable results
        data = bytes([0x00, 0x7B, 0x01])  # 0x007B = 123, 0x01 = 1 ("on" in map)

        # Parse with our test model
        result = parser.parse(data, "test_model", 256)

        # Check the result contains the expected fields
        assert result == {"test_field": 123, "test_field_with_map": "on"}


def test_parse_partial_data():
    """Test parsing partial data for a supported model."""
    # Create a mock parser with a controlled register map
    test_register_map = {
        "test_model": {
            "test_field1": {
                "register": 256,
                "length": 2,
                "byte_order": "big",
                "offset": 0,
            },
            "test_field2": {
                "register": 256,
                "length": 2,
                "byte_order": "big",
                "offset": 2,
            },
        }
    }

    # Set up logging capture
    log_capture = io.StringIO()
    log_handler = logging.StreamHandler(log_capture)
    logger = logging.getLogger("renogy_ble.parser")
    logger.addHandler(log_handler)
    logger.setLevel(logging.WARNING)

    try:
        with patch("renogy_ble.parser.REGISTER_MAP", test_register_map):
            parser = RenogyBaseParser()

            # Create data that's only enough for the first field
            data = bytes([0x00, 0x2A])  # 0x002A = 42

            # Parse with our test model
            result = parser.parse(data, "test_model", 256)

            # Check the result contains only the first field
            assert len(result) == 1
            assert result == {"test_field1": 42}

            # Check that a warning was logged
            log_output = log_capture.getvalue()
            assert "Unexpected data length" in log_output
    finally:
        # Clean up logger
        logger.removeHandler(log_handler)


@pytest.fixture
def controller_parser():
    """Fixture that returns a ControllerParser instance."""
    return ControllerParser()


def test_parse_data(controller_parser):
    """Test that parse_data calls the base parse method with the controller type."""
    # Set up mock to return a dummy result
    with patch.object(ControllerParser, "parse") as mock_parse:
        mock_parse.return_value = {"battery_voltage": 12.6}

        # Create some dummy data
        data = bytes([0x01, 0x02, 0x03, 0x04])

        # Call parse_data with the register parameter (fixed)
        result = controller_parser.parse_data(data, register=256)

        # Check the result matches what we expect
        assert result == {"battery_voltage": 12.6}

        # Check that parse was called with the correct arguments
        mock_parse.assert_called_once_with(data, "controller", 256)


@pytest.fixture
def integration_test_data():
    """Fixture that provides real sample data for integration tests."""
    return {
        12: b"\xff\x03\x10  RNG-CTRL-RVR407$",
        26: b"\xff\x03\x02\x00\x10\x90\\",
        256: (
            b"\xff\x03D\x00d\x00\x90\x00\x04\x0e\x19\x00\x00\x00\x00\x00\x00\x00\xe8"
            b"\x00\x04\x00\x01\x00\x00\x00\x8f\x00\x91\x00\x11\x00\x00\x00\x01\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02+\x00\x01\x00\x00\x00\x00\x13|"
            b"\x00\x00\x00\x00\x00\x01\x01\x90\x00\x00\x00\x00\x00\x04\x00\x00\xa3\xd2"
        ),
        57348: b"\xff\x03\x02\x00\x04\x90S",
    }


@pytest.fixture
def integration_parser():
    """
    Fixture that sets up a RenogyBaseParser with log capture for integration
    tests.
    """
    parser = RenogyBaseParser()

    # Capture log output for testing warnings
    log_capture = io.StringIO()
    log_handler = logging.StreamHandler(log_capture)
    logger = logging.getLogger("renogy_ble.parser")
    logger.addHandler(log_handler)
    logger.setLevel(logging.WARNING)

    yield parser, log_capture

    # Clean up logger
    logger.removeHandler(log_handler)


def test_controller_parsing_register_12(integration_parser, integration_test_data):
    """Test parsing real device info data (register 12) for the controller type."""
    parser, _ = integration_parser
    result = parser.parse(integration_test_data[12], "controller", 12)

    assert isinstance(result, dict)
    assert "model" in result
    assert result["model"] == "RNG-CTRL-RVR"


def test_controller_parsing_register_26(integration_parser, integration_test_data):
    """Test parsing real device address data (register 26) for the controller type."""
    parser, _ = integration_parser
    result = parser.parse(integration_test_data[26], "controller", 26)

    assert isinstance(result, dict)
    assert "device_id" in result
    assert result["device_id"] == 16


def test_controller_parsing_register_256(integration_parser, integration_test_data):
    """Test parsing real charging info data (register 256) for the controller type."""
    parser, _ = integration_parser
    result = parser.parse(integration_test_data[256], "controller", 256)

    assert isinstance(result, dict)

    # Test a few specific fields
    assert "battery_voltage" in result
    assert result["battery_voltage"] == 14.4

    assert "battery_percentage" in result
    assert result["battery_percentage"] == 100

    assert "charging_status" in result
    assert result["charging_status"] == "boost"

    # Check that we got the expected number of fields
    assert len(result) >= 18  # This should match the number of fields in register 256


def test_controller_negative_temperatures(
    integration_parser, integration_test_data
):
    """Ensure temperature bytes are parsed as signed values."""
    parser, _ = integration_parser
    data = bytearray(integration_test_data[256])

    data[9] = 0xFF  # controller_temperature -> -1
    data[10] = 0xF0  # battery_temperature -> -16

    result = parser.parse(bytes(data), "controller", 256)

    assert result["controller_temperature"] == -1
    assert result["battery_temperature"] == -16


def test_controller_parsing_register_57348(integration_parser, integration_test_data):
    """Test parsing real battery type data (register 57348) for the controller type."""
    parser, _ = integration_parser
    result = parser.parse(integration_test_data[57348], "controller", 57348)

    assert isinstance(result, dict)
    assert "battery_type" in result
    assert result["battery_type"] == "lithium"


def test_partial_data_parsing(integration_parser):
    """Test parsing with truncated data for a specific register."""
    parser, log_capture = integration_parser

    # Create a simplified register map for testing partial data
    test_register_map = {
        "controller": {
            "field1": {
                "register": 256,
                "length": 2,
                "byte_order": "big",
                "offset": 0,
            },
            "field2": {
                "register": 256,
                "length": 2,
                "byte_order": "big",
                "offset": 2,
            },
            "field3": {
                "register": 256,
                "length": 2,
                "byte_order": "big",
                "offset": 4,
            },
        }
    }

    with patch("renogy_ble.parser.REGISTER_MAP", test_register_map):
        # Create a new parser instance with the patched REGISTER_MAP
        parser = RenogyBaseParser()

        # Create data that's only enough for the first field
        data = bytes([0x01, 0x02])

        result = parser.parse(data, "controller", 256)

        # Check that we only got the first field
        assert len(result) == 1
        assert "field1" in result
        assert "field2" not in result
        assert "field3" not in result

        # Check that a warning was logged about unexpected data length
        log_output = log_capture.getvalue()
        assert "Unexpected data length" in log_output


def test_unsupported_model(integration_parser):
    """Test parsing with an unsupported model."""
    parser, log_capture = integration_parser

    data = bytes([0x01, 0x02, 0x03, 0x04])
    result = parser.parse(data, "nonexistent_model", 256)

    # Check that we get an empty dictionary
    assert result == {}

    # Check that a warning was logged
    log_output = log_capture.getvalue()
    assert "Unsupported model" in log_output
