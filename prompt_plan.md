# Prompt 1: Project Initialization

Create the following project structure for the "Renogy BLE Data Parsing Library":

renogy_ble/
├── __init__.py         # Empty file to initialize the package
├── parser.py           # Placeholder for parser implementation
├── register_map.py     # Placeholder for register mapping definitions
├── setup.py            # Placeholder for packaging metadata
└── tests/
    └── test_parser.py  # Placeholder for unit tests

Provide the content for each file as empty or with minimal placeholder content, ensuring that the directory structure is clear.

# Prompt 2: Implement Register Map

In the file "register_map.py", define a dictionary named REGISTER_MAP that includes a sample mapping for the "rover" model. For example, include the following fields:

- battery_voltage: register 256, length 2, byte_order "big"
- pv_power: register 260, length 2, byte_order "little"
- charging_status: register 270, length 1, with a mapping of {0: "deactivated", 2: "mppt"} and byte_order "big"

Also, include comments explaining the structure of the dictionary. Output the complete content of "register_map.py".

# Prompt 3: Develop Base Parsing Functions

In the file "parser.py", implement the following:
1. A helper function called `parse_value(data, offset, length, byte_order)` that takes raw bytes and converts them into an integer using the specified byte order.
2. A class `RenogyBaseParser` that:
   - Loads the REGISTER_MAP from "register_map.py".
   - Iterates through each field defined in the map for a given model.
   - Uses `parse_value` to extract the raw integer value.
   - Handles cases where the provided data is shorter than expected by logging a warning (you can use the `warnings` module) and returning only the successfully parsed fields.

Output the complete content of "parser.py" with these implementations.

# Prompt 4: Build the Model-Specific Parser

Extend the implementation in "parser.py" by creating a class `RoverParser` that inherits from `RenogyBaseParser`. Implement any Rover-specific parsing logic if needed (even if it just calls the base implementation for now). The `RoverParser` should produce a flat dictionary of raw values as defined in the register mapping.

Output the updated content of "parser.py" with the new `RoverParser` class.

# Prompt 5: Create the Entry Point Parser

In the package's "__init__.py" (or in a separate module if you prefer), create an entry point class or function called `RenogyParser` with a static method `parse(raw_data, model)`. This method should:
1. Check the model parameter.
2. If the model is "rover", instantiate and use the `RoverParser` to parse the raw data.
3. If the model is not supported (i.e., not found in REGISTER_MAP), log a warning and return an empty dictionary.

Output the complete content for the entry point that wires everything together.

# Prompt 6: Add Error Handling and Logging

Enhance the parser implementation by:
1. Adding warnings in `RenogyBaseParser` for when the raw data is shorter than expected. The warning should state: "Warning: Unexpected data length, partial parsing attempted."
2. Ensuring that even if the data is truncated or does not completely match the expected length, the parser returns a dictionary with the fields that were successfully parsed.

Update the relevant portions in "parser.py" and output the revised content.

# Prompt 7: Write Unit Tests

In the file "tests/test_parser.py", write a suite of unit tests for the following scenarios:
1. Valid full data parsing for the Rover model: provide sample raw bytes and verify that the parsed output contains the correct raw integer values.
2. Partial data parsing: simulate truncated raw data and verify that a warning is logged and that only the available fields are returned.
3. Unsupported model handling: pass a model that is not defined in the REGISTER_MAP and check that an empty dictionary is returned with a warning.

Output the complete content of "tests/test_parser.py" with these unit tests.

# Prompt 8: Packaging and Final Integration

Prepare the packaging files for the project:
1. In "setup.py", provide the metadata (name, version, author, description, URL, classifiers) for the library.
2. Optionally, include a basic "pyproject.toml" if needed for the build system.
3. Ensure that all the code written in previous prompts is integrated, and that there are no orphaned modules or functions.

Output the final content of "setup.py" (and "pyproject.toml" if applicable) to complete the project packaging.