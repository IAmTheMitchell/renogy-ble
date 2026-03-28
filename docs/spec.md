# Renogy BLE Library - Developer Specification

## **Overview**
This document outlines the design, requirements, and implementation details for
a standalone Python library that communicates with Renogy devices over BLE,
builds and validates Modbus requests, and parses the returned data. The library
supports controller-style devices using BT-1 and BT-2 modules, dedicated
inverter BLE flows, and direct Smart Shunt 300 BLE notifications. Home
Assistant-specific lifecycle and entity behavior remain out of scope.

---

## **1. Functional Requirements**

### **1.1 Supported Devices**
- Supports **Renogy charge controllers** using BT-1 and BT-2 modules.
- Supports **Renogy DC-DC chargers** that share the controller-style Modbus flow.
- Supports **Renogy inverters** using the inverter-specific BLE transport.
- Supports **Renogy Smart Shunt 300** devices via direct BLE notifications.

### **1.2 Features**
- Connects to supported Renogy BLE devices and reads their telemetry.
- Parses **raw BLE Modbus data** from controller-style devices and inverters.
- Extracts **battery, solar input, load output, controller status, inverter status, and energy stats**.
- Uses a **flat dictionary structure** (e.g., `{ "battery_voltage": 129, "pv_power": 250 }`).
- Applies device-specific scaling and mapping where required.
- Validates Modbus framing and logs warnings for **unexpected data lengths** while attempting partial parsing where possible.

---

## **2. Architecture**

### **2.1 Library Structure**
```
renogy_ble/
  ├── __init__.py         # Entry point
  ├── ble.py              # BLE transport and read flows
  ├── parser.py           # Main parser logic
  ├── register_map.py     # Register definitions for each model
  ├── shunt.py            # Smart Shunt 300 BLE client
  ├── pyproject.toml      # Build system support
  └── tests/
      ├── test_ble.py     # Unit tests for BLE transport and parsing integration
      ├── test_parser.py  # Unit tests for parsing logic
```

### **2.2 Components**
#### **1️⃣ `register_map.py` (Register Definitions)**
- Stores **register mappings** for different models.
- Defines **byte order** for each field.
- Example format:
  ```python
  REGISTER_MAP = {
      "rover": {
          "battery_voltage": {"register": 256, "length": 2, "byte_order": "big"},
          "pv_power": {"register": 260, "length": 2, "byte_order": "little"},
          "charging_status": {
              "register": 270,
              "length": 1,
              "map": {0: "deactivated", 2: "mppt"},
              "byte_order": "big"
          }
      }
  }
  ```

#### **2️⃣ `RenogyBaseParser` (Base Class for Parsing)**
- Loads **register mappings** from `register_map.py`.
- Extracts **raw values** based on byte order.
- Supports **partial parsing** if data is incomplete.

#### **3️⃣ `RoverParser` (Model-Specific Parser)**
- Extends `RenogyBaseParser`.
- Implements **Rover-specific parsing logic**.

#### **4️⃣ `RenogyBleClient` and `RenogyParser` (Entry Points)**
- `RenogyBleClient` handles BLE communication, Modbus framing, and device-specific read flows.
- `RenogyParser` routes raw data to the correct model parser when BLE I/O is handled externally.
- API:
  ```python
  from renogy_ble import RenogyParser
  raw_data = b"\x00\x81"  # Example BLE response
  parsed = RenogyParser.parse(raw_data, model="rover")
  print(parsed)  # {'battery_voltage': 129}
  ```

---

## **3. Data Handling**

### **3.1 Input Format**
- Accepts **raw BLE Modbus response bytes** when parsing existing frames.
- Supports full end-to-end BLE reads when the caller provides a discovered BLE device plus a supported `device_type`.

### **3.2 Output Format**
- Returns a **flat dictionary** of parsed values, e.g.:
  ```python
  {
      "battery_voltage": 12.9,
      "pv_power": 250,
      "charging_status": "mppt"
  }
```

### **3.3 Byte Order Handling**
- Defined per **register** in `register_map.py`.
- Supports **big-endian** and **little-endian** formats.
- Example implementation:
  ```python
  def parse_value(data, offset, length, byte_order="big"):
      value = int.from_bytes(data[offset:offset+length], byteorder=byte_order)
      return value
  ```

---

## **4. Error Handling**

### **4.1 Malformed Data**
- If the response length is **shorter than expected**:
  - Logs a warning: `"Warning: Unexpected data length, partial parsing attempted."`
  - Returns a **partial dictionary** with available fields.

### **4.2 Unsupported Model**
- If the model is **not in `register_map.py`**:
  - Logs a warning: `"Warning: Unsupported model: unknown_model"`
  - Returns `{}`.

### **4.3 Unknown Data**
- If the response format **does not match expected registers**:
  - Logs a warning but **still returns whatever fields can be parsed**.

---

## **5. Testing Plan**

### **5.1 Unit Tests (`tests/test_parser.py`)**
- ✅ **Test valid data parsing**
  - Ensure raw bytes are correctly mapped to dictionary values.
  - Verify handling of **different byte orders**.
- ✅ **Test partial parsing**
  - Provide truncated data and ensure expected partial output.
- ✅ **Test unsupported models**
  - Pass an invalid model and check that `{}` is returned.
- ✅ **Test unexpected data length**
  - Log warning and return partial data.

Example test case:
```python
import unittest
from renogy_ble import RenogyParser

class TestRenogyParser(unittest.TestCase):
    def test_rover_parsing(self):
        raw_data = b"\x00\x81\x00\xFA"  # Fake response
        parsed = RenogyParser.parse(raw_data, model="rover")
        self.assertEqual(parsed["battery_voltage"], 129)
```

---

## **6. Packaging & Deployment**

### **6.1 PyPI Packaging**
- Library will be published as `renogy-ble`.
- Installable via:
  ```sh
  pip install renogy-ble
  ```

### **6.2 `setup.py` (Example Metadata)**
```python
from setuptools import setup, find_packages

setup(
    name="renogy-ble",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[],
    author="Your Name",
    description="Python library for parsing BLE data from Renogy charge controllers.",
    url="https://github.com/yourrepo/renogy-ble",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
    ],
)
```

---

## **7. Next Steps**
- ✅ Finalize `register_map.py` for Rover.
- ✅ Implement `RenogyBaseParser` and `RoverParser`.
- ✅ Write unit tests.
- ✅ Package and publish to PyPI.

---

## **Final Notes**
This library is designed for **Home Assistant integration** but can be used in any project that needs **raw Renogy BLE data parsing**. The architecture allows **easy expansion** to other models in the future.
