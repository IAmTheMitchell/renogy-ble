# TODO: Renogy BLE Data Parsing Library

This checklist outlines every task required to build, test, and package the Renogy BLE Data Parsing Library.

---

## 1. Project Setup and Structure
- [x] Create the main project directory (e.g., `renogy_ble/`)
- [x] Create the following folder structure:
  - `renogy_ble/`
    - `__init__.py` (empty file)
    - `parser.py` (placeholder for parser logic)
    - `register_map.py` (placeholder for register mappings)
  - `tests/`
    - `test_parser.py` (placeholder for unit tests)
- [x] Create `setup.py` in the project root for packaging metadata

---

## 2. Register Map Definition
- [x] Open `register_map.py`
- [x] Define a dictionary named `REGISTER_MAP` with the following:
  - [x] **Rover Model** mapping:
    - `battery_voltage`: 
      - register: 256 
      - length: 2 
      - byte_order: "big"
    - `pv_power`: 
      - register: 260 
      - length: 2 
      - byte_order: "little"
    - `charging_status`: 
      - register: 270 
      - length: 1 
      - map: `{0: "deactivated", 2: "mppt"}` 
      - byte_order: "big"
- [x] Add comments explaining the structure and purpose of the register definitions

---

## 3. Base Parsing Logic
- [x] In `parser.py`, implement a helper function:
  - [x] `parse_value(data, offset, length, byte_order)` to extract integers from raw bytes based on byte order
- [x] Create a class `RenogyBaseParser`:
  - [x] Load the `REGISTER_MAP` from `register_map.py`
  - [x] Iterate through each field for a given model and extract data using `parse_value`
  - [x] Handle cases where raw data is shorter than expected:
    - [x] Log a warning: "Warning: Unexpected data length, partial parsing attempted."
    - [x] Return a partial dictionary with only the fields that could be parsed

---

## 4. Model-Specific Parser
- [x] Create a class `RoverParser` in `parser.py`:
  - [x] Inherit from `RenogyBaseParser`
  - [x] Implement Rover-specific parsing logic (if needed)
  - [x] Ensure output is a flat dictionary of raw values

---

## 5. Entry Point Parser
- [x] In `__init__.py` (or a separate module), create an entry point called `RenogyParser`:
  - [x] Implement a static method `parse(raw_data, model)` that:
    - [x] Checks the provided model
    - [x] Routes the raw data to `RoverParser` if the model is "rover"
    - [x] Logs a warning and returns an empty dictionary if the model is unsupported
- [x] Integrate `RenogyParser` with the rest of the package

---

## 6. Error Handling and Logging
- [x] Enhance error handling in `RenogyBaseParser`:
  - [x] Log warnings for unexpected or insufficient data length
  - [x] Ensure the parser returns a partial dictionary when data is truncated
- [x] Verify that all logging is informative and follows best practices

---

## 7. Testing
- [ ] In `tests/test_parser.py`, write unit tests to cover:
  - [ ] Valid full data parsing for the Rover model:
    - [ ] Provide complete raw bytes and verify that the output matches expected values
  - [ ] Partial data parsing:
    - [ ] Simulate truncated data and verify a warning is logged and partial results are returned
  - [ ] Unsupported model handling:
    - [ ] Pass an invalid model and verify that an empty dictionary is returned with a warning
  - [ ] Correct handling of byte orders (big-endian and little-endian)
- [ ] Run tests and ensure all tests pass

---

## 8. Packaging and Deployment
- [ ] Complete `setup.py` with:
  - [ ] Project name (e.g., `renogy-ble`)
  - [ ] Version (e.g., `0.1.0`)
  - [ ] Author information
  - [ ] Description of the library
  - [ ] URL to the repository
  - [ ] Classifiers (including Python version and license)
- [ ] Optionally create a basic `pyproject.toml` for build system support
- [ ] Test package installation locally using `pip install -e .`
- [ ] Verify that the library is importable and functioning as expected

---

## 9. Documentation and Final Checks
- [ ] Review the entire codebase for consistency and integration
- [ ] Update comments and documentation as needed
- [ ] Ensure there is no orphaned or unused code in the project
- [ ] Prepare a README.md that describes the project, usage, and contribution guidelines
- [ ] Commit all changes and prepare the repository for version control