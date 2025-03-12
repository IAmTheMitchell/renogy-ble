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
#             "map": dict (optional)     # Optional value mapping for enum-like fields
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
            "byte_order": "big"
        },
        # Device address section (register 26)
        "device_id": {
            "register": 26,
            "length": 1,
            "byte_order": "big"
        },
        # Charging info section (register 256)
        "battery_percentage": {
            "register": 256,
            "length": 2,
            "byte_order": "big"
        },
        "battery_voltage": {
            "register": 256,
            "length": 2,
            "byte_order": "big",
            "scale": 0.1
        },
        "battery_current": {
            "register": 256,
            "length": 2,
            "byte_order": "big",
            "scale": 0.01
        },
        "controller_temperature": {
            "register": 256,
            "length": 1,
            "byte_order": "big"
        },
        "battery_temperature": {
            "register": 256,
            "length": 1,
            "byte_order": "big"
        },
        "load_status": {
            "register": 256,
            "length": 1,
            "byte_order": "big",
            "map": {
                0: "off",
                1: "on"
            }
        },
        "load_voltage": {
            "register": 256,
            "length": 2,
            "byte_order": "big",
            "scale": 0.1
        },
        "load_current": {
            "register": 256,
            "length": 2,
            "byte_order": "big",
            "scale": 0.01
        },
        "load_power": {
            "register": 256,
            "length": 2,
            "byte_order": "big"
        },
        "pv_voltage": {
            "register": 256,
            "length": 2,
            "byte_order": "big",
            "scale": 0.1
        },
        "pv_current": {
            "register": 256,
            "length": 2,
            "byte_order": "big",
            "scale": 0.01
        },
        "pv_power": {
            "register": 256,
            "length": 2,
            "byte_order": "big"
        },
        "max_charging_power_today": {
            "register": 256,
            "length": 2,
            "byte_order": "big"
        },
        "max_discharging_power_today": {
            "register": 256,
            "length": 2,
            "byte_order": "big"
        },
        "charging_amp_hours_today": {
            "register": 256,
            "length": 2,
            "byte_order": "big"
        },
        "discharging_amp_hours_today": {
            "register": 256,
            "length": 2,
            "byte_order": "big"
        },
        "power_generation_today": {
            "register": 256,
            "length": 2,
            "byte_order": "big"
        },
        "power_consumption_today": {
            "register": 256,
            "length": 2,
            "byte_order": "big"
        },
        "power_generation_total": {
            "register": 256,
            "length": 4,
            "byte_order": "big"
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
                6: "current limiting"
            }
        },
        # Battery type section (register 57348)
        "battery_type": {
            "register": 57348,
            "length": 2,
            "byte_order": "big",
            "map": {
                1: "open",
                2: "sealed",
                3: "gel",
                4: "lithium",
                5: "custom"
            }
        }
    }
}
