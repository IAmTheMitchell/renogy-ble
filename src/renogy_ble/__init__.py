"""
Renogy BLE Parser Package

This package provides functionality to parse data from Renogy BLE devices.
It supports different device models by routing the parsing to type-specific parsers.
"""

import logging

from renogy_ble.battery import (
    BATTERY_DEVICE_TYPE,
    BATTERY_VARIANT_LEGACY,
    BATTERY_VARIANT_PRO,
    BATTERY_VARIANT_RNGPRO,
    detect_battery_variant,
    is_supported_battery_name,
)
from renogy_ble.ble import (
    COMMANDS,
    DEFAULT_DEVICE_ID,
    DEFAULT_DEVICE_TYPE,
    LOAD_CONTROL_REGISTER,
    MAX_NOTIFICATION_WAIT_TIME,
    RENOGY_READ_CHAR_UUID,
    RENOGY_WRITE_CHAR_UUID,
    RIV4835CSH1S_MODEL,
    RenogyBleClient,
    RenogyBLEDevice,
    RenogyBleReadResult,
    RenogyBleWriteResult,
    clean_device_name,
    create_modbus_read_request,
    create_modbus_write_request,
    modbus_crc,
)
from renogy_ble.hub import (
    HUB_BATTERY_SLAVE_IDS,
    RenogyCommunicationHub,
    RenogyHubBattery,
    RenogyHubBatteryReadResult,
)
from renogy_ble.identification import (
    BATTERY_PRO_MANUFACTURER_ID,
    RENOGY_BATTERY_PRO_PREFIXES,
    RENOGY_BT_PREFIX,
    RENOGY_INVERTER_PREFIX,
    RENOGY_REGO_INVERTER_PREFIX,
    SHUNT300_BT_PREFIX,
    SUPPORTED_BLE_NAME_PREFIXES,
    AdvertisementIdentity,
    DeviceType,
    detect_device_type_from_model,
    expected_prefixes_for_device_type,
    identify_advertisement,
    is_address_placeholder,
    name_matches_device_type,
)
from renogy_ble.renogy_parser import RenogyParser
from renogy_ble.settings import DeviceSetting, SettingValue, get_device_settings
from renogy_ble.shunt import (
    KEY_SHUNT_CURRENT,
    KEY_SHUNT_ENERGY_CHARGED_TOTAL,
    KEY_SHUNT_ENERGY_DISCHARGED_TOTAL,
    KEY_SHUNT_POWER,
    KEY_SHUNT_SOC,
    KEY_SHUNT_VOLTAGE,
    ShuntBleClient,
    ShuntNotificationDecoder,
    ShuntSubscription,
    parse_shunt_payload,
)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


__all__ = [
    "AdvertisementIdentity",
    "DeviceType",
    "identify_advertisement",
    "detect_device_type_from_model",
    "is_address_placeholder",
    "name_matches_device_type",
    "expected_prefixes_for_device_type",
    "SUPPORTED_BLE_NAME_PREFIXES",
    "BATTERY_PRO_MANUFACTURER_ID",
    "RENOGY_BT_PREFIX",
    "RENOGY_INVERTER_PREFIX",
    "RENOGY_REGO_INVERTER_PREFIX",
    "RENOGY_BATTERY_PRO_PREFIXES",
    "SHUNT300_BT_PREFIX",
    "DeviceSetting",
    "SettingValue",
    "get_device_settings",
    "COMMANDS",
    "BATTERY_DEVICE_TYPE",
    "BATTERY_VARIANT_LEGACY",
    "BATTERY_VARIANT_PRO",
    "BATTERY_VARIANT_RNGPRO",
    "DEFAULT_DEVICE_ID",
    "DEFAULT_DEVICE_TYPE",
    "HUB_BATTERY_SLAVE_IDS",
    "LOAD_CONTROL_REGISTER",
    "MAX_NOTIFICATION_WAIT_TIME",
    "RENOGY_READ_CHAR_UUID",
    "RENOGY_WRITE_CHAR_UUID",
    "RIV4835CSH1S_MODEL",
    "RenogyBLEDevice",
    "RenogyBleClient",
    "RenogyBleReadResult",
    "RenogyBleWriteResult",
    "RenogyCommunicationHub",
    "RenogyHubBattery",
    "RenogyHubBatteryReadResult",
    "RenogyParser",
    "clean_device_name",
    "create_modbus_read_request",
    "create_modbus_write_request",
    "detect_battery_variant",
    "is_supported_battery_name",
    "modbus_crc",
    "KEY_SHUNT_VOLTAGE",
    "KEY_SHUNT_CURRENT",
    "KEY_SHUNT_POWER",
    "KEY_SHUNT_SOC",
    "KEY_SHUNT_ENERGY_CHARGED_TOTAL",
    "KEY_SHUNT_ENERGY_DISCHARGED_TOTAL",
    "parse_shunt_payload",
    "ShuntBleClient",
    "ShuntNotificationDecoder",
    "ShuntSubscription",
]
