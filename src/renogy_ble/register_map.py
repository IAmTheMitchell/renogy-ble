"""
Register Map for Renogy BLE devices

This module contains register mapping definitions for different Renogy device models.
These mappings are used by the parser module to correctly interpret raw byte data.
"""

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

REGISTER_MAP = {
    "rover": {
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
        },
        "battery_temperature": {
            "register": 256,
            "length": 1,
            "byte_order": "big",
            "offset": 10,
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
    }
}
