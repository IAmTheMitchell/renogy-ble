"""Opt-in LCD settings and raw diagnostics for RIV4835CSH1S.

The read plan contains settings compared with the physical LCD and raw firmware
fields returned by that installation. It excludes unresolved register probes.
No Home Assistant dependencies or inverter writes are used here.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from time import monotonic
from typing import TYPE_CHECKING, Any

from .ble import (
    INVERTER_DEVICE_ID,
    INVERTER_INIT_CHAR_UUID,
    INVERTER_INIT_DELAY,
    INVERTER_INTER_COMMAND_DELAY,
    RIV4835CSH1S_MODEL,
    modbus_crc,
)

if TYPE_CHECKING:
    from .ble import RenogyBleClient, RenogyBLEDevice

# These short blocks were read successfully on the RIV installation.
# Readability and LCD comparisons do not certify other firmware revisions.
READ_BLOCKS = (
    (4393, 1),
    (4398, 4),
    (4405, 1),
    (4422, 1),
    (4424, 14),
    (4439, 6),
    (4447, 1),
    (4101, 1),
)
REFRESH_SECONDS = 900
_RESPONSE_HEX_LIMIT = 64
_EXCEPTION_NAMES = {
    1: "Unsupported function code",
    2: "Invalid register address or read length",
    3: "Invalid read length",
    4: "Device could not read registers",
    5: "Request checksum error",
}

PROGRAMS = {
    1: (4441, 1, {0: "SOL", 1: "UTI", 2: "SBU"}),
    2: (4442, 100, None),
    3: (4443, 1, {0: "APL", 1: "UPS"}),
    4: (4437, 10, None),
    5: (4439, 10, None),
    6: (4447, 1, {0: "CSo", 1: "Cub", 2: "SnU", 3: "oSo"}),
    7: (4422, 10, None),
    8: (
        4424,
        1,
        {
            0: "USE",
            1: "SLd",
            2: "FLd",
            3: "GEL",
            4: "LF14",
            5: "LF15",
            6: "LF16",
            12: "N13",
            13: "N14",
        },
    ),
    9: (4426, 10, None),
    10: (4435, 1, None),
    11: (4427, 10, None),
    12: (4431, 10, None),
    13: (4433, 1, None),
    14: (4430, 10, None),
    15: (4432, 10, None),
    17: (4425, 10, None),
    18: (4434, 1, None),
    19: (4440, 1, None),
    20: (4436, 1, None),
    22: (4444, 1, {0: "DIS", 1: "ENA", 2: "Sleep"}),
    25: (4101, 1, {0: "ENA", 1: "DIS"}),
    35: (4429, 10, None),
    37: (4428, 10, None),
}

NATIVE_PROGRAMS = {
    23: (57869, 1, {0: "DIS", 1: "ENA"}),
    24: (57870, 1, {0: "DIS", 1: "ENA"}),
    26: (57873, 1, {0: "DIS", 1: "ENA"}),
    27: (57874, 1, {0: "DIS", 1: "ENA"}),
    36: (57345, 10, None),
    38: (57864, 10, None),
}

LCD_NAMES = {
    1: ("Output Priority", None),
    2: ("Output Frequency", "Hz"),
    3: ("AC Input Voltage Range", None),
    4: ("Battery to Utility Setpoint", "V"),
    5: ("Utility to Battery Setpoint", "V"),
    6: ("Battery Charging Mode", None),
    7: ("Maximum Total Charging Current", "A"),
    8: ("Battery Type", None),
    9: ("Boost Charge Voltage", "V"),
    10: ("Boost Charge Duration", "min"),
    11: ("Float Charge Voltage", "V"),
    12: ("Low Voltage Load Disconnect", "V"),
    13: ("Overdischarge Delay", "s"),
    14: ("Low Voltage Warning", "V"),
    15: ("Discharge Limit Voltage", "V"),
    17: ("Equalization Voltage", "V"),
    18: ("Equalization Duration", "min"),
    19: ("Equalization Timeout", "min"),
    20: ("Equalization Interval", "d"),
    22: ("Power Saving Mode", None),
    23: ("Overload Automatic Restart", None),
    24: ("Overtemperature Automatic Restart", None),
    25: ("Buzzer Alarm", None),
    26: ("Mode Transition Alarm", None),
    27: ("Overload Bypass", None),
    35: ("Low Voltage Disconnect Recovery", "V"),
    36: ("PV Charging Current", "A"),
    37: ("Boost Return Setpoint", "V"),
    38: ("AC Output Voltage Setting", "V"),
}

MACHINE_STATES = {
    0: "Power-on delay",
    1: "Wait",
    2: "Initialization",
    3: "Soft start",
    4: "Grid",
    5: "Inverter",
    6: "Inverter to grid",
    7: "Grid to inverter",
    8: "Hybrid",
    9: "Reserved",
    10: "Shutdown",
    11: "Fault",
    12: "Load sense",
}

LCD_FAULT_NAMES = {
    1: "Battery undervoltage alert",
    2: "Battery discharge software overcurrent",
    3: "Battery not detected",
    4: "Battery undervoltage stop-discharge alarm",
    5: "Battery hardware overcurrent",
    6: "Charging overvoltage protection",
    7: "Bus hardware overvoltage",
    8: "Bus software overvoltage",
    9: "PV overvoltage protection",
    10: "Buck software overcurrent",
    11: "Buck hardware overcurrent",
    12: "AC input power loss",
    13: "Bypass overload",
    14: "Inverter overload",
    15: "Inverter hardware overcurrent",
    17: "Inverter short circuit",
    19: "Controller overtemperature",
    20: "Inverter overtemperature",
    21: "Fan failure",
    22: "Memory failure",
    23: "Model setting error",
    26: "Relay short circuit",
    29: "Bus undervoltage",
}


def _describe_failed_response(data: Any, count: int) -> dict[str, Any]:
    """Inspect existing bytes without accepting unvalidated rejection frames."""
    details: dict[str, Any] = {"expected_byte_count": 5 + count * 2}
    if not isinstance(data, (bytes, bytearray)):
        return {**details, "status": "buffer_unavailable"}
    buffered = bytes(data)
    details.update(
        {
            "status": "invalid_response" if buffered else "no_bytes",
            "received_byte_count": len(buffered),
            "response_hex": buffered[:_RESPONSE_HEX_LIMIT].hex(" ").upper(),
            "response_truncated": len(buffered) > _RESPONSE_HEX_LIMIT,
        }
    )
    # The transport clears this buffer immediately before the locked FC03 read.
    # It retains rejected frames until the failed session is disconnected.
    for offset in range(len(buffered) - 4):
        candidate = buffered[offset : offset + 5]
        if candidate[:2] != bytes((INVERTER_DEVICE_ID, 0x83)):
            continue
        if candidate[-2:] != bytes(modbus_crc(candidate[:-2])):
            continue
        code = candidate[2]
        details.update(
            {
                "status": "modbus_exception",
                "crc_validated": True,
                "exception_code": code,
                "exception_name": _EXCEPTION_NAMES.get(code, "Unknown exception code"),
                "exception_response_hex": candidate.hex(" ").upper(),
            }
        )
    return details


def _missing_response_error(details: dict[str, Any]) -> str:
    """Separate silent reads, rejected registers, and invalid received data."""
    if details["status"] == "modbus_exception":
        return (
            f"Modbus exception 0x{details['exception_code']:02X}: "
            f"{details['exception_name']}"
        )
    if details["status"] == "no_bytes":
        return "No diagnostic response: no bytes received within 2.0 s"
    if details["status"] == "invalid_response":
        return (
            "No valid diagnostic response: "
            f"received {details['received_byte_count']} bytes, "
            f"expected {details['expected_byte_count']} bytes"
        )
    return "No valid diagnostic response; transport buffer unavailable"


def _decode_words(response: bytes, count: int) -> list[int]:
    """Validate framing again before exposing optional diagnostic values."""
    if (
        len(response) != 5 + count * 2
        or response[:3] != bytes((INVERTER_DEVICE_ID, 3, count * 2))
        or response[-2:] != bytes(modbus_crc(response[:-2]))
    ):
        raise ValueError("Invalid diagnostic Modbus response")
    return [
        int.from_bytes(response[3 + i * 2 : 5 + i * 2], "big") for i in range(count)
    ]


# The words are raw decimal values; firmware component labels remain unresolved.
FIRMWARE_BLOCKS = ((0x0014, 1), (0x0015, 1), (0x10DF, 8))
SLOW_BLOCKS = (
    tuple((register, 1) for register, _, _ in NATIVE_PROGRAMS.values())
    + FIRMWARE_BLOCKS
)


@dataclass(frozen=True)
class InverterDiagnosticField:
    """A read-only display field with native units and no write capability."""

    key: str
    name: str
    unit: str | None = None
    precision: int | None = None


def get_inverter_diagnostic_fields(
    model_hint: str | None,
) -> tuple[InverterDiagnosticField, ...]:
    """Return only the RIV model's validated reading surface."""
    if model_hint != RIV4835CSH1S_MODEL:
        return ()
    programs = tuple(
        InverterDiagnosticField(
            f"riv_program_{program:02d}",
            f"LCD {program:02d} {name}",
            unit,
            1 if unit in {"V", "A"} else 2 if unit == "Hz" else 0 if unit else None,
        )
        for program, (name, unit) in LCD_NAMES.items()
    )
    other = (
        ("riv_operating_state", "Operating State"),
        ("riv_active_faults", "Active Faults"),
        ("riv_fault_count", "Active Fault Count"),
        ("riv_fault_decode_status", "Fault Description Status"),
        ("riv_warning_mask", "Warning Mask"),
        ("riv_warning_bits_set", "Warning Bits Set"),
        ("riv_active_warnings", "Active Warnings"),
        ("riv_warning_definition_status", "Warning Definition Status"),
        ("riv_diagnostic_read_status", "Diagnostic Read Status"),
        *(
            (f"riv_fault_code_{slot}", f"Fault Code Slot {slot}")
            for slot in range(1, 5)
        ),
        ("riv_research_word_0014", "Software Version Word 0x0014"),
        ("riv_research_word_0015", "Software Version Word 0x0015"),
        ("riv_research_word_10df", "SDK Firmware Text Candidate"),
    )
    return programs + tuple(InverterDiagnosticField(key, name) for key, name in other)


def _next_slow_block(
    cache: dict[str, dict[str, Any]], now: datetime
) -> tuple[int, int] | None:
    """Complete one bounded first pass before refreshing native LCD settings."""
    for block in SLOW_BLOCKS:
        if str(block[0]) not in cache:
            return block
    for block in SLOW_BLOCKS:
        evidence = cache[str(block[0])]
        if evidence["read_status"] == "unsupported":
            continue
        if block in FIRMWARE_BLOCKS and evidence["read_status"] == "read":
            continue
        due = evidence.get("next_read_at")
        if due is None or datetime.fromisoformat(due) <= now:
            return block
    return None


def _field_evidence(
    register: int, evidence: dict[str, Any] | None, *, index: int = 0
) -> dict[str, Any]:
    """Keep raw values and validation separate from semantic decoding."""
    evidence = evidence or {}
    words = evidence.get("raw_words")
    raw = words[index] if isinstance(words, list) and index < len(words) else None
    status = evidence.get("read_status", "not_read")
    if status == "read" and raw == 0xFFFF:
        status = "unsupported"
    result = {
        "register": register,
        "register_hex": f"0x{register:04X}",
        "raw_value": raw,
        "raw_hex": f"0x{raw:04X}" if raw is not None else None,
        "read_status": status,
        "sampled_at": evidence.get("sampled_at"),
        "last_attempt_at": evidence.get("last_attempt_at"),
        "next_read_at": evidence.get("next_read_at"),
        "read_response": evidence.get("read_response"),
        "cached": evidence.get("cached", False),
    }
    if "read_error" in evidence:
        result["read_error"] = evidence["read_error"]
    return result


def _decode_firmware(words: list[int]) -> str | None:
    """Accept the SDK's exact printable ASCII block, with optional NUL padding."""
    raw = b"".join(word.to_bytes(2, "big") for word in words)
    text, _, padding = raw.partition(b"\x00")
    if not text or any(padding) or any(byte < 32 or byte > 126 for byte in text):
        return None
    return text.decode("ascii")


def _snapshot(cache: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Expose only successful current reads and explicitly timestamped caches."""
    fields: dict[str, dict[str, Any]] = {}
    values: dict[str, Any] = {}
    words: dict[int, tuple[int | None, dict[str, Any], int]] = {}
    for start, count in READ_BLOCKS + SLOW_BLOCKS:
        evidence = cache.get(str(start))
        if not evidence:
            continue
        raw_words = evidence.get("raw_words") or []
        for index in range(count):
            raw = raw_words[index] if index < len(raw_words) else None
            words[start + index] = raw, evidence, index
    for program, (register, divisor, labels) in (PROGRAMS | NATIVE_PROGRAMS).items():
        key = f"riv_program_{program:02d}"
        raw, evidence, index = words.get(register, (None, None, 0))
        details = _field_evidence(register, evidence, index=index)
        details.update(
            {
                "lcd_program": program,
                "protocol_divisor": divisor,
                "mapping_status": "protocol_mapping_with_model_lcd_comparison",
            }
        )
        fields[key] = details
        if details["read_status"] == "read" and raw is not None:
            values[key] = (
                labels.get(raw, f"Unknown ({raw})") if labels else raw / divisor
            )
    raw, evidence, index = words.get(4405, (None, None, 0))
    details = _field_evidence(4405, evidence, index=index)
    fields["riv_operating_state"] = details
    if details["read_status"] == "read" and raw is not None:
        values["riv_operating_state"] = MACHINE_STATES.get(raw, f"Unknown ({raw})")
    slots = []
    for slot in range(1, 5):
        register = 4397 + slot
        raw, evidence, index = words.get(register, (None, None, 0))
        details = _field_evidence(register, evidence, index=index)
        fields[f"riv_fault_code_{slot}"] = details
        if details["read_status"] == "read" and raw is not None:
            values[f"riv_fault_code_{slot}"] = raw
            slots.append(raw)
    if len(slots) == 4:
        active = [code for code in slots if code]
        values["riv_fault_count"] = len(active)
        values["riv_active_faults"] = (
            "; ".join(
                f"{code:02d}: {LCD_FAULT_NAMES.get(code, 'Unverified for this model')}"
                for code in active
            )
            or "None"
        )
        known = [code in LCD_FAULT_NAMES for code in active]
        values["riv_fault_decode_status"] = (
            "no_active_codes"
            if not active
            else "lcd_manual"
            if all(known)
            else "unverified_for_model"
            if not any(known)
            else "mixed"
        )
        for key in ("riv_fault_count", "riv_active_faults", "riv_fault_decode_status"):
            fields[key] = {
                **_field_evidence(4398, cache.get("4398")),
                "fault_slots": slots,
                "description_source": "RIV4835CSH1S LCD manual",
            }
    raw, evidence, index = words.get(4393, (None, None, 0))
    details = _field_evidence(4393, evidence, index=index)
    details["mapping_status"] = "warning_definitions_unverified_for_model"
    for key in (
        "riv_warning_mask",
        "riv_warning_bits_set",
        "riv_active_warnings",
        "riv_warning_definition_status",
    ):
        fields[key] = dict(details)
    if details["read_status"] == "read" and raw is not None:
        bits = [bit for bit in range(16) if raw & (1 << bit)]
        values.update(
            {
                "riv_warning_mask": raw,
                "riv_warning_bits_set": ", ".join(map(str, bits)) or "None",
                "riv_active_warnings": f"Unverified (0x{raw:04X})",
                "riv_warning_definition_status": "unverified_for_model",
            }
        )
        for key in (
            "riv_warning_mask",
            "riv_warning_bits_set",
            "riv_active_warnings",
            "riv_warning_definition_status",
        ):
            fields[key]["bits_set"] = bits
    for register in (0x0014, 0x0015):
        key = f"riv_research_word_{register:04x}"
        details = _field_evidence(register, cache.get(str(register)))
        details["mapping_status"] = "raw_word_component_identity_unverified"
        fields[key] = details
        if details["read_status"] == "read":
            values[key] = details["raw_value"]
    evidence = cache.get(str(0x10DF), {})
    details = _field_evidence(0x10DF, evidence)
    details.update(
        {
            "raw_words": evidence.get("raw_words"),
            "register_count": 8,
            "mapping_status": "ascii_read_component_identities_unverified",
        }
    )
    fields["riv_research_word_10df"] = details
    if evidence.get("read_status") == "read":
        text = _decode_firmware(evidence["raw_words"])
        if text is not None:
            values["riv_research_word_10df"] = text
    pending = any(str(register) not in cache for register, _ in SLOW_BLOCKS)
    failed = any(item.get("read_status") != "read" for item in cache.values())
    values["riv_diagnostic_read_status"] = (
        "pending" if pending else "partial" if failed else "complete"
    )
    values["riv_diagnostics"] = {
        "sampled_at": datetime.now(timezone.utc).isoformat(),
        "fields": fields,
        "register_reads": cache,
        "read_errors": {
            register: evidence["read_error"]
            for register, evidence in cache.items()
            if "read_error" in evidence
        },
        "polling": {
            "ordinary_blocks_per_poll": len(READ_BLOCKS),
            "maximum_extra_requests_per_poll": 1,
            "refresh_seconds": REFRESH_SECONDS,
            "firmware_refresh": "once_after_success_until_reader_reload",
            "unsupported_retry": "after_reader_reload_only",
        },
    }
    return values


async def async_read_inverter_diagnostics(
    client: RenogyBleClient,
    device: RenogyBLEDevice,
    *,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Read the bounded RIV plan using the same transport and lock as controls."""
    if device.device_type != "inverter" or device.model_hint != RIV4835CSH1S_MODEL:
        raise ValueError("Diagnostics require the RIV4835CSH1S inverter profile")
    prior = (previous or {}).get("register_reads", {})
    cache = {
        str(register): {**prior[str(register)], "cached": True}
        for register, _ in READ_BLOCKS + SLOW_BLOCKS
        if isinstance(prior.get(str(register)), dict)
    }
    slow = _next_slow_block(cache, datetime.now(timezone.utc))
    plan = READ_BLOCKS + ((slow,) if slow is not None else ())
    for register, count in plan:
        old = cache.get(str(register), {})
        if old.get("read_status") == "unsupported":
            continue
        attempted_at = datetime.now(timezone.utc)
        evidence: dict[str, Any] = {
            "last_attempt_at": attempted_at.isoformat(),
            "sampled_at": None,
            "raw_words": None,
            "cached": False,
        }
        # Drop a failed session before another same-length response can arrive.
        session = await client._prepare_session(device)
        async with session.lock:
            completed = False
            response = None
            read_attempted = False
            started = monotonic()
            try:
                await client._ensure_session_ready(device, session)
                if session.client is None:
                    raise RuntimeError("Diagnostic BLE session is not connected")
                await asyncio.sleep(INVERTER_INIT_DELAY)
                try:
                    await session.client.read_gatt_char(INVERTER_INIT_CHAR_UUID)
                except Exception:
                    pass
                read_attempted = True
                response = await client._read_modbus_register(
                    session,
                    device_id=INVERTER_DEVICE_ID,
                    function_code=3,
                    register=register,
                    word_count=count,
                    cmd_name=f"RIV diagnostics {register}",
                    device_name=device.name,
                    timeout=2.0,
                    retries=1,
                )
                if response is None:
                    evidence["read_response"] = _describe_failed_response(
                        session.notification_data, count
                    )
                    raise TimeoutError(
                        _missing_response_error(evidence["read_response"])
                    )
                raw_words = _decode_words(response, count)
                evidence.update(
                    {
                        "raw_words": raw_words,
                        "sampled_at": attempted_at.isoformat(),
                        "read_response": {
                            "status": "read",
                            "crc_validated": True,
                            "expected_byte_count": 5 + count * 2,
                            "received_byte_count": len(response),
                            "response_hex": response.hex(" ").upper(),
                            "response_truncated": False,
                        },
                    }
                )
                completed = True
            except Exception as exc:
                evidence["read_error"] = str(exc)
                if read_attempted and "read_response" not in evidence:
                    evidence["read_response"] = _describe_failed_response(
                        response if response is not None else session.notification_data,
                        count,
                    )
            finally:
                if "read_response" in evidence:
                    evidence["read_response"]["elapsed_ms"] = round(
                        (monotonic() - started) * 1000, 1
                    )
                if not completed or client._transport_mode != "persistent_session":
                    await client._close_session(
                        device.address, device.name, session, remove=not completed
                    )
        successful_words = evidence.get("raw_words") or []
        rejected = (
            evidence.get("read_response", {}).get("crc_validated") is True
            and evidence["read_response"].get("exception_code") == 2
        )
        evidence["read_status"] = (
            "unsupported"
            if rejected
            or (completed and all(raw == 0xFFFF for raw in successful_words))
            else "read"
            if completed
            else "read_error"
        )
        if (
            register == 0x10DF
            and evidence["read_status"] == "read"
            and _decode_firmware(successful_words) is None
        ):
            evidence["read_status"] = "read_error"
            evidence["read_error"] = (
                "Firmware text block is empty or not printable ASCII"
            )
        static_success = (register, count) in FIRMWARE_BLOCKS and evidence[
            "read_status"
        ] == "read"
        evidence["next_read_at"] = (
            None
            if evidence["read_status"] == "unsupported" or static_success
            else (attempted_at + timedelta(seconds=REFRESH_SECONDS)).isoformat()
        )
        cache[str(register)] = evidence
        await asyncio.sleep(INVERTER_INTER_COMMAND_DELAY)
    return _snapshot(cache)
