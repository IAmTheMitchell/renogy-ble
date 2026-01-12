"""
Register Map for Renogy BLE devices

This module contains register mapping definitions for different Renogy device models.
These mappings are used by the parser module to correctly interpret raw byte data.
"""

from typing import Literal, TypedDict

# REGISTER_MAP structure:
# {
#     "model_name": {
#         "field_name": {
#             "register": int,           # Register number (address)
#             "length": int,             # Length in bytes
#             "byte_order": str,         # "big" or "little" endian
#             "offset": int,             # Offset within the response data
#             "map": dict (optional)     # Optional value mapping for enum-like fields
#             "scale": float (optional)  # Optional scaling factor
#         },
#         # more fields...
#     },
#     # more models...
# }


class FieldInfo(TypedDict, total=False):
    """Describe how a register field should be decoded."""

    register: int
    length: int
    byte_order: Literal["big", "little"]
    offset: int
    map: dict[int, str]
    scale: float
    bit_offset: int
    data_type: Literal["int", "string"]
    signed: bool
    signed_encoding: Literal["twos_complement", "sign_magnitude"]


RegisterMap = dict[str, dict[str, FieldInfo]]


REGISTER_MAP: RegisterMap = {
    "controller": {
        # Device info section (register 12)
        "model": {
            "register": 12,
            "length": 14,  # bytes 3-17
            "byte_order": "big",
            "offset": 3,
            "data_type": "string",
        },
        # Device address section (register 26)
        "device_id": {"register": 26, "length": 1, "byte_order": "big", "offset": 4},
        # Charging info section (register 256)
        "battery_percentage": {
            "register": 256,
            "length": 2,
            "byte_order": "big",
            "offset": 3,
        },
        "battery_voltage": {
            "register": 256,
            "length": 2,
            "byte_order": "big",
            "scale": 0.1,
            "offset": 5,
        },
        "battery_current": {
            "register": 256,
            "length": 2,
            "byte_order": "big",
            "scale": 0.01,
            "offset": 7,
        },
        "controller_temperature": {
            "register": 256,
            "length": 1,
            "byte_order": "big",
            "offset": 9,
            "signed": True,
            "signed_encoding": "sign_magnitude",
        },
        "battery_temperature": {
            "register": 256,
            "length": 1,
            "byte_order": "big",
            "offset": 10,
            "signed": True,
            "signed_encoding": "sign_magnitude",
        },
        "load_status": {
            "register": 256,
            "length": 1,
            "byte_order": "big",
            "map": {0: "off", 1: "on"},
            "offset": 67,
            "bit_offset": 7,  # High bit of byte at offset 67
        },
        "load_voltage": {
            "register": 256,
            "length": 2,
            "byte_order": "big",
            "scale": 0.1,
            "offset": 11,
        },
        "load_current": {
            "register": 256,
            "length": 2,
            "byte_order": "big",
            "scale": 0.01,
            "offset": 13,
        },
        "load_power": {"register": 256, "length": 2, "byte_order": "big", "offset": 15},
        "pv_voltage": {
            "register": 256,
            "length": 2,
            "byte_order": "big",
            "scale": 0.1,
            "offset": 17,
        },
        "pv_current": {
            "register": 256,
            "length": 2,
            "byte_order": "big",
            "scale": 0.01,
            "offset": 19,
        },
        "pv_power": {"register": 256, "length": 2, "byte_order": "big", "offset": 21},
        "max_charging_power_today": {
            "register": 256,
            "length": 2,
            "byte_order": "big",
            "offset": 33,
        },
        "max_discharging_power_today": {
            "register": 256,
            "length": 2,
            "byte_order": "big",
            "offset": 35,
        },
        "charging_amp_hours_today": {
            "register": 256,
            "length": 2,
            "byte_order": "big",
            "offset": 37,
        },
        "discharging_amp_hours_today": {
            "register": 256,
            "length": 2,
            "byte_order": "big",
            "offset": 39,
        },
        "power_generation_today": {
            "register": 256,
            "length": 2,
            "byte_order": "big",
            "offset": 41,
        },
        "power_consumption_today": {
            "register": 256,
            "length": 2,
            "byte_order": "big",
            "offset": 43,
        },
        "power_generation_total": {
            "register": 256,
            "length": 4,
            "byte_order": "big",
            "offset": 59,
        },
        "charging_status": {
            "register": 256,
            "length": 1,
            "byte_order": "big",
            "map": {
                0: "deactivated",
                1: "activated",
                2: "mppt",
                3: "equalizing",
                4: "boost",
                5: "floating",
                6: "current limiting",
            },
            "offset": 68,
        },
        # Battery type section (register 57348)
        "battery_type": {
            "register": 57348,
            "length": 2,
            "byte_order": "big",
            "map": {1: "open", 2: "sealed", 3: "gel", 4: "lithium", 5: "custom"},
            "offset": 3,
        },
    },
    # DCC (DC-DC Charger) device type
    # Based on DCC Charger Controller Modbus Protocol V1.0
    "dcc": {
        # Device info section (register 12)
        "model": {
            "register": 12,
            "length": 14,
            "byte_order": "big",
            "offset": 3,
            "data_type": "string",
        },
        # Device address section (register 26)
        "device_id": {"register": 26, "length": 1, "byte_order": "big", "offset": 4},
        # Dynamic Data Section (register 256 / 0x0100)
        # Battery/House battery data
        "battery_soc": {
            "register": 256,
            "length": 2,
            "byte_order": "big",
            "offset": 3,
        },
        "battery_voltage": {
            "register": 256,
            "length": 2,
            "byte_order": "big",
            "scale": 0.1,
            "offset": 5,
        },
        "total_charging_current": {
            "register": 256,
            "length": 2,
            "byte_order": "big",
            "scale": 0.01,
            "offset": 7,
        },
        # Temperature data (same offsets as controller)
        "controller_temperature": {
            "register": 256,
            "length": 1,
            "byte_order": "big",
            "offset": 9,
            "signed": True,
            "signed_encoding": "sign_magnitude",
        },
        "battery_temperature": {
            "register": 256,
            "length": 1,
            "byte_order": "big",
            "offset": 10,
            "signed": True,
            "signed_encoding": "sign_magnitude",
        },
        # Alternator/Generator data (0x0104-0x0106)
        "alternator_voltage": {
            "register": 256,
            "length": 2,
            "byte_order": "big",
            "scale": 0.1,
            "offset": 11,
        },
        "alternator_current": {
            "register": 256,
            "length": 2,
            "byte_order": "big",
            "scale": 0.01,
            "offset": 13,
        },
        "alternator_power": {
            "register": 256,
            "length": 2,
            "byte_order": "big",
            "offset": 15,
        },
        # Solar data (0x0107-0x0109)
        "solar_voltage": {
            "register": 256,
            "length": 2,
            "byte_order": "big",
            "scale": 0.1,
            "offset": 17,
        },
        "solar_current": {
            "register": 256,
            "length": 2,
            "byte_order": "big",
            "scale": 0.01,
            "offset": 19,
        },
        "solar_power": {
            "register": 256,
            "length": 2,
            "byte_order": "big",
            "offset": 21,
        },
        # Daily statistics (0x010B-0x0113)
        "daily_min_battery_voltage": {
            "register": 256,
            "length": 2,
            "byte_order": "big",
            "scale": 0.1,
            "offset": 25,
        },
        "daily_max_battery_voltage": {
            "register": 256,
            "length": 2,
            "byte_order": "big",
            "scale": 0.1,
            "offset": 27,
        },
        "daily_max_charging_current": {
            "register": 256,
            "length": 2,
            "byte_order": "big",
            "scale": 0.01,
            "offset": 29,
        },
        "daily_max_charging_power": {
            "register": 256,
            "length": 2,
            "byte_order": "big",
            "offset": 33,
        },
        "daily_charging_ah": {
            "register": 256,
            "length": 2,
            "byte_order": "big",
            "offset": 37,
        },
        "daily_power_generation": {
            "register": 256,
            "length": 2,
            "byte_order": "big",
            "scale": 0.001,  # Returns kWh
            "offset": 41,
        },
        # Lifetime statistics (0x0115-0x011D)
        "total_operating_days": {
            "register": 256,
            "length": 2,
            "byte_order": "big",
            "offset": 45,
        },
        "total_overdischarge_count": {
            "register": 256,
            "length": 2,
            "byte_order": "big",
            "offset": 47,
        },
        "total_full_charge_count": {
            "register": 256,
            "length": 2,
            "byte_order": "big",
            "offset": 49,
        },
        "total_charging_ah": {
            "register": 256,
            "length": 4,
            "byte_order": "big",
            "offset": 51,
        },
        "total_power_generation": {
            "register": 256,
            "length": 4,
            "byte_order": "big",
            "scale": 0.001,  # Returns kWh
            "offset": 59,
        },
        # Status section (register 288 / 0x0120)
        "charging_status": {
            "register": 288,
            "length": 1,
            "byte_order": "big",
            "map": {
                0: "standby",
                2: "mppt",
                3: "equalizing",
                4: "boost",
                5: "floating",
                6: "current_limiting",
                8: "dc_mode",
            },
            "offset": 4,  # Low byte of 0x0120
        },
        # Fault information (register 289-290 / 0x0121-0x0122)
        "fault_high": {
            "register": 289,
            "length": 2,
            "byte_order": "big",
            "offset": 3,
        },
        "fault_low": {
            "register": 290,
            "length": 2,
            "byte_order": "big",
            "offset": 3,
        },
        # Output power (register 292 / 0x0124)
        "output_power": {
            "register": 292,
            "length": 2,
            "byte_order": "big",
            "offset": 3,
        },
        # Charging mode (register 293 / 0x0125)
        "charging_mode": {
            "register": 293,
            "length": 2,
            "byte_order": "big",
            "map": {
                0: "standby",
                1: "alternator_to_house",
                2: "house_to_starter",
                3: "solar_to_house",
                4: "solar_alternator_to_house",
                5: "solar_to_starter",
            },
            "offset": 3,
        },
        # Ignition signal (register 294 / 0x0126)
        "ignition_status": {
            "register": 294,
            "length": 2,
            "byte_order": "big",
            "map": {0: "disconnected", 1: "connected"},
            "offset": 3,
        },
        # Maximum charging current (register 57345 / 0xE001)
        # Stored as centiamps (100x), so 4000 = 40A
        "max_charging_current": {
            "register": 57345,
            "length": 2,
            "byte_order": "big",
            "offset": 3,
            "scale": 0.01,  # Convert centiamps to amps
        },
        # Parameter Settings Section (all read from register 57347 / 0xE003)
        # Command reads 18 words starting at 0xE003, offsets are within the response
        "system_voltage": {
            "register": 57347,
            "length": 1,
            "byte_order": "big",
            "offset": 3,
        },
        "battery_type": {
            "register": 57347,
            "length": 2,
            "byte_order": "big",
            "map": {0: "custom", 1: "open", 2: "sealed", 3: "gel", 4: "lithium"},
            "offset": 5,
        },
        "overvoltage_threshold": {
            "register": 57347,
            "length": 2,
            "byte_order": "big",
            "scale": 0.1,
            "offset": 7,
        },
        "charging_limit_voltage": {
            "register": 57347,
            "length": 2,
            "byte_order": "big",
            "scale": 0.1,
            "offset": 9,
        },
        "equalization_voltage": {
            "register": 57347,
            "length": 2,
            "byte_order": "big",
            "scale": 0.1,
            "offset": 11,
        },
        "boost_voltage": {
            "register": 57347,
            "length": 2,
            "byte_order": "big",
            "scale": 0.1,
            "offset": 13,
        },
        "float_voltage": {
            "register": 57347,
            "length": 2,
            "byte_order": "big",
            "scale": 0.1,
            "offset": 15,
        },
        "boost_return_voltage": {
            "register": 57347,
            "length": 2,
            "byte_order": "big",
            "scale": 0.1,
            "offset": 17,
        },
        "overdischarge_return_voltage": {
            "register": 57347,
            "length": 2,
            "byte_order": "big",
            "scale": 0.1,
            "offset": 19,
        },
        "undervoltage_warning": {
            "register": 57347,
            "length": 2,
            "byte_order": "big",
            "scale": 0.1,
            "offset": 21,
        },
        "overdischarge_voltage": {
            "register": 57347,
            "length": 2,
            "byte_order": "big",
            "scale": 0.1,
            "offset": 23,
        },
        "discharge_limit_voltage": {
            "register": 57347,
            "length": 2,
            "byte_order": "big",
            "scale": 0.1,
            "offset": 25,
        },
        "overdischarge_delay": {
            "register": 57347,
            "length": 2,
            "byte_order": "big",
            "offset": 29,
        },
        "equalization_time": {
            "register": 57347,
            "length": 2,
            "byte_order": "big",
            "offset": 31,
        },
        "boost_time": {
            "register": 57347,
            "length": 2,
            "byte_order": "big",
            "offset": 33,
        },
        "equalization_interval": {
            "register": 57347,
            "length": 2,
            "byte_order": "big",
            "offset": 35,
        },
        "temperature_compensation": {
            "register": 57347,
            "length": 2,
            "byte_order": "big",
            "offset": 37,
        },
    },
}
