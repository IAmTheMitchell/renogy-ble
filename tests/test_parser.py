"""
Unit tests for the Renogy BLE parser implementation.

This module tests the functionality of the parser module to ensure it correctly
parses raw byte data according to the register mapping definitions.
"""

import unittest
import logging
from unittest.mock import patch, MagicMock
import io

# Import the modules to be tested
from parser import RenogyBaseParser, RoverParser, parse_value

class TestParseValue(unittest.TestCase):
    """Test cases for the parse_value helper function."""
    
    def test_parse_value_big_endian(self):
        """Test parsing a value with big-endian byte order."""
        data = bytes([0x01, 0x02, 0x03, 0x04, 0x05])
        
        # Test parsing 2 bytes from offset 1 with big-endian byte order
        value = parse_value(data, 1, 2, 'big')
        self.assertEqual(value, 0x0203)
        
    def test_parse_value_little_endian(self):
        """Test parsing a value with little-endian byte order."""
        data = bytes([0x01, 0x02, 0x03, 0x04, 0x05])
        
        # Test parsing 2 bytes from offset 2 with little-endian byte order
        value = parse_value(data, 2, 2, 'little')
        self.assertEqual(value, 0x0403)
    
    def test_parse_value_insufficient_data(self):
        """Test parsing a value with insufficient data."""
        data = bytes([0x01, 0x02, 0x03])
        
        # Test parsing 2 bytes from offset 2, which only has 1 byte available
        with self.assertRaises(ValueError):
            parse_value(data, 2, 2, 'big')


class TestRenogyBaseParser(unittest.TestCase):
    """Test cases for the RenogyBaseParser class."""
    
    def setUp(self):
        """Set up the test environment."""
        self.parser = RenogyBaseParser()
    
    @patch('parser.logger')
    def test_parse_unsupported_model(self, mock_logger):
        """Test parsing data with an unsupported model."""
        # Create some dummy data
        data = bytes([0x01, 0x02, 0x03, 0x04])
        
        # Parse with an unsupported model
        result = self.parser.parse(data, "unsupported_model")
        
        # Check that the result is an empty dictionary
        self.assertEqual(result, {})
        
        # Check that a warning was logged
        mock_logger.warning.assert_called_with("Unsupported model: %s", "unsupported_model")
    
    def test_parse_full_data(self):
        """Test parsing full data for a supported model."""
        # Create a mock parser with a controlled register map
        test_register_map = {
            "test_model": {
                "test_field": {
                    "register": 256,
                    "length": 2,
                    "byte_order": "big"
                },
                "test_field_with_map": {
                    "register": 258,
                    "length": 1,
                    "byte_order": "big",
                    "map": {1: "on", 0: "off"}
                }
            }
        }
        
        with patch('parser.REGISTER_MAP', test_register_map):
            parser = RenogyBaseParser()
            
            # Create test data with values that should produce predictable results
            data = bytes([0x00, 0x7B, 0x01])  # 0x007B = 123, 0x01 = 1 ("on" in map)
            
            # Parse with our test model
            result = parser.parse(data, "test_model")
            
            # Check the result contains the expected fields
            self.assertEqual(result, {"test_field": 123, "test_field_with_map": "on"})
    
    def test_parse_partial_data(self):
        """Test parsing partial data for a supported model."""
        # Create a mock parser with a controlled register map
        test_register_map = {
            "test_model": {
                "test_field1": {
                    "register": 256,
                    "length": 2,
                    "byte_order": "big"
                },
                "test_field2": {
                    "register": 258,
                    "length": 2,
                    "byte_order": "big"
                }
            }
        }
        
        # Set up logging capture
        log_capture = io.StringIO()
        log_handler = logging.StreamHandler(log_capture)
        logger = logging.getLogger('parser')
        logger.addHandler(log_handler)
        logger.setLevel(logging.WARNING)
        
        try:
            with patch('parser.REGISTER_MAP', test_register_map):
                parser = RenogyBaseParser()
                
                # Create data that's only enough for the first field
                data = bytes([0x00, 0x2A])  # 0x002A = 42
                
                # Parse with our test model
                result = parser.parse(data, "test_model")
                
                # Check the result contains only the first field
                self.assertEqual(len(result), 1)
                self.assertEqual(result, {"test_field1": 42})
                
                # Check that a warning was logged
                log_output = log_capture.getvalue()
                self.assertIn("Unexpected data length", log_output)
        finally:
            # Clean up logger
            logger.removeHandler(log_handler)


class TestRoverParser(unittest.TestCase):
    """Test cases for the RoverParser class."""
    
    def setUp(self):
        """Set up the test environment."""
        self.parser = RoverParser()
    
    @patch.object(RoverParser, 'parse')
    def test_parse_data(self, mock_parse):
        """Test that parse_data calls the base parse method with the rover model."""
        # Set up mock to return a dummy result
        mock_parse.return_value = {"battery_voltage": 12.6}
        
        # Create some dummy data
        data = bytes([0x01, 0x02, 0x03, 0x04])
        
        # Call parse_data
        result = self.parser.parse_data(data)
        
        # Check the result matches what we expect
        self.assertEqual(result, {"battery_voltage": 12.6})
        
        # Check that parse was called with the correct arguments
        mock_parse.assert_called_once_with(data, "rover")


class TestIntegration(unittest.TestCase):
    """Integration tests for the parser using actual register map data."""
    
    def setUp(self):
        """Set up the test environment."""
        self.parser = RenogyBaseParser()
        
        # Capture log output for testing warnings
        self.log_capture = io.StringIO()
        self.log_handler = logging.StreamHandler(self.log_capture)
        logger = logging.getLogger('parser')
        logger.addHandler(self.log_handler)
        logger.setLevel(logging.WARNING)
    
    def tearDown(self):
        """Clean up after the tests."""
        # Remove the log handler
        logger = logging.getLogger('parser')
        logger.removeHandler(self.log_handler)
    
    def test_rover_model_parsing(self):
        """Test parsing real data for the Rover model."""
        # Create sample data that would match the registers in the Rover model
        # This data should be long enough to cover all expected registers
        data = bytes([
            # Create a sample sequence long enough for the test
            0x32, 0x00, 0x04, 0xD2, 0x01, 0x2C, 0x28, 0x01, 0x05, 0x0A,
            0x00, 0x64, 0x00, 0xC8, 0x01, 0x90, 0x02, 0x58, 0x03, 0x20,
            0x03, 0xE8, 0x04, 0xB0, 0x05, 0x78, 0x06, 0x40, 0x07, 0x08,
            0x07, 0xD0, 0x08, 0x98, 0x09, 0x60, 0x0A, 0x28, 0x0A, 0xF0,
            0x01, 0x00, 0x00, 0x00, 0x02
        ])
        
        result = self.parser.parse(data, "rover")
        
        # Verify we got some data back
        self.assertIsInstance(result, dict)
        self.assertGreater(len(result), 0)
        
        # For battery_percentage specifically
        if "battery_percentage" in result:
            self.assertEqual(result["battery_percentage"], 0x3200)
    
    def test_partial_data_parsing(self):
        """Test parsing with truncated data for the Rover model."""
        # Create a simplified register map for testing partial data
        test_register_map = {
            "rover": {
                "field1": {"register": 256, "length": 2, "byte_order": "big"},
                "field2": {"register": 258, "length": 2, "byte_order": "big"},
                "field3": {"register": 260, "length": 2, "byte_order": "big"}
            }
        }
            
        with patch('parser.REGISTER_MAP', test_register_map):
            # Create a new parser instance with the patched REGISTER_MAP
            parser = RenogyBaseParser()
            
            # Create data that's only enough for the first field
            data = bytes([0x01, 0x02])
            
            result = parser.parse(data, "rover")
            
            # Check that we only got the first field
            self.assertEqual(len(result), 1)
            self.assertIn("field1", result)
            self.assertNotIn("field2", result)
            self.assertNotIn("field3", result)
            
            # Check that a warning was logged about unexpected data length
            log_output = self.log_capture.getvalue()
            self.assertIn("Unexpected data length", log_output)
    
    def test_unsupported_model(self):
        """Test parsing with an unsupported model."""
        data = bytes([0x01, 0x02, 0x03, 0x04])
        
        result = self.parser.parse(data, "nonexistent_model")
        
        # Check that we get an empty dictionary
        self.assertEqual(result, {})
        
        # Check that a warning was logged
        log_output = self.log_capture.getvalue()
        self.assertIn("Unsupported model", log_output)


if __name__ == '__main__':
    unittest.main()