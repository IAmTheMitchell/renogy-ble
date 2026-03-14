"""
Renogy BLE Parser Package

This package provides functionality to parse data from Renogy BLE devices.
It supports different device models by routing the parsing to type-specific parsers.
"""

import logging

from renogy_ble.ble import (
    COMMANDS,
    DEFAULT_DEVICE_ID,
    DEFAULT_DEVICE_TYPE,
    LOAD_CONTROL_REGISTER,
    MAX_NOTIFICATION_WAIT_TIME,
    RENOGY_READ_CHAR_UUID,
    RENOGY_WRITE_CHAR_UUID,
    RenogyBleClient,
    RenogyBLEDevice,
    RenogyBleReadResult,
    RenogyBleWriteResult,
    clean_device_name,
    create_modbus_read_request,
    create_modbus_write_request,
    modbus_crc,
)
from renogy_ble.inverter import (
    INVERTER_COMMANDS,
    INVERTER_DEVICE_ID,
    INVERTER_INIT_CHAR_UUID,
    InverterBleClient,
)
from renogy_ble.renogy_parser import RenogyParser
from renogy_ble.shunt import (
    KEY_SHUNT_CURRENT,
    KEY_SHUNT_ENERGY_CHARGED_TOTAL,
    KEY_SHUNT_ENERGY_DISCHARGED_TOTAL,
    KEY_SHUNT_POWER,
    KEY_SHUNT_SOC,
    KEY_SHUNT_VOLTAGE,
    ShuntBleClient,
    parse_shunt_payload,
)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


__all__ = [
    "COMMANDS",
    "DEFAULT_DEVICE_ID",
    "DEFAULT_DEVICE_TYPE",
    "INVERTER_COMMANDS",
    "INVERTER_DEVICE_ID",
    "INVERTER_INIT_CHAR_UUID",
    "LOAD_CONTROL_REGISTER",
    "MAX_NOTIFICATION_WAIT_TIME",
    "RENOGY_READ_CHAR_UUID",
    "RENOGY_WRITE_CHAR_UUID",
    "RenogyBLEDevice",
    "RenogyBleClient",
    "RenogyBleReadResult",
    "RenogyBleWriteResult",
    "RenogyParser",
    "clean_device_name",
    "create_modbus_read_request",
    "create_modbus_write_request",
    "modbus_crc",
    "InverterBleClient",
    "KEY_SHUNT_VOLTAGE",
    "KEY_SHUNT_CURRENT",
    "KEY_SHUNT_POWER",
    "KEY_SHUNT_SOC",
    "KEY_SHUNT_ENERGY_CHARGED_TOTAL",
    "KEY_SHUNT_ENERGY_DISCHARGED_TOTAL",
    "parse_shunt_payload",
    "ShuntBleClient",
]
