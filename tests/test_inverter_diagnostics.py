"""Exercise the optional RIV reader through actual Modbus serialization."""

import asyncio
from unittest.mock import MagicMock

import pytest

from renogy_ble import (
    RIV4835CSH1S_MODEL,
    RenogyBleClient,
    RenogyBLEDevice,
    get_inverter_diagnostic_fields,
    modbus_crc,
)
from renogy_ble import ble as transport
from renogy_ble import inverter_diagnostics as diagnostics


def frame(words, device_id=32, function=3):
    payload = bytes([device_id, function, len(words) * 2])
    payload += b"".join(word.to_bytes(2, "big") for word in words)
    return payload + bytes(modbus_crc(payload))


def ascii_words(text):
    raw = text.encode("ascii").ljust(16, b"\x00")
    return [int.from_bytes(raw[i : i + 2], "big") for i in range(0, 16, 2)]


class DiagnosticTransport:
    """Feed split notifications to the production response validator."""

    def __init__(self):
        self.requests = []
        self.overrides = {}
        self.is_connected = True
        self.handler = None
        # Independent expected readings from the LCD and captured firmware.
        self.words = {
            4393: 50,
            4398: 0,
            4399: 0,
            4400: 0,
            4401: 0,
            4405: 5,
            4422: 800,
            4424: 5,
            4425: 540,
            4426: 540,
            4427: 540,
            4428: 508,
            4429: 504,
            4430: 496,
            4431: 448,
            4432: 428,
            4433: 30,
            4434: 0,
            4435: 120,
            4436: 0,
            4437: 492,
            4439: 536,
            4440: 5,
            4441: 2,
            4442: 6000,
            4443: 1,
            4444: 0,
            4447: 2,
            4101: 0,
            0xE20D: 1,
            0xE20E: 1,
            0xE211: 1,
            0xE212: 1,
            0xE001: 800,
            0xE208: 1200,
            0x0014: 403,
            0x0015: 107,
        }
        self.words.update(
            {0x10DF + i: word for i, word in enumerate(ascii_words("300*107*160*403"))}
        )

    async def connect(self, *_args, **_kwargs):
        self.is_connected = True
        return self

    async def start_notify(self, _target, handler):
        self.handler = handler

    async def write_gatt_char(self, _target, payload):
        request = bytes(payload)
        self.requests.append(request)
        assert request[:2] == b"\x20\x03"
        assert request[-2:] == bytes(modbus_crc(request[:-2]))
        register = int.from_bytes(request[2:4], "big")
        count = int.from_bytes(request[4:6], "big")
        response = self.overrides.get(
            register,
            frame([self.words.get(register + offset, 0) for offset in range(count)]),
        )
        if response is not None:
            assert self.handler is not None
            self.handler(None, response[:3])
            self.handler(None, response[3:])

    async def read_gatt_char(self, _target):
        return b"\x00"

    async def stop_notify(self, _target):
        pass

    async def disconnect(self):
        self.is_connected = False


@pytest.fixture
def wire(monkeypatch):
    fake = DiagnosticTransport()
    monkeypatch.setattr(transport, "establish_connection", fake.connect)
    monkeypatch.setattr(diagnostics, "INVERTER_INIT_DELAY", 0)
    monkeypatch.setattr(diagnostics, "INVERTER_INTER_COMMAND_DELAY", 0)
    original_read = RenogyBleClient._read_modbus_register

    async def fast_read(self, session, **kwargs):
        kwargs["timeout"] = 0.002
        return await original_read(self, session, **kwargs)

    monkeypatch.setattr(RenogyBleClient, "_read_modbus_register", fast_read)
    return fake


def device(kind="inverter", model=RIV4835CSH1S_MODEL):
    ble = MagicMock(address="AA:BB:CC:DD:EE:FF")
    ble.name = "BT-TH-test"
    return RenogyBLEDevice(ble, device_type=kind, model_hint=model)


async def complete_pass(client, target):
    result = {}
    for _ in range(9):
        result = await client.read_inverter_diagnostics(
            target, previous=result.get("riv_diagnostics")
        )
    return result


def test_validated_lcd_surface_and_raw_diagnostics(wire):
    target = device()
    target.parsed_data = {"battery_voltage": 50.6}
    client = RenogyBleClient(transport_mode="persistent_session")
    result = asyncio.run(complete_pass(client, target))
    expected = {
        "riv_program_01": "SBU",
        "riv_program_02": 60.0,
        "riv_program_03": "UPS",
        "riv_program_04": 49.2,
        "riv_program_05": 53.6,
        "riv_program_06": "SnU",
        "riv_program_07": 80.0,
        "riv_program_08": "LF15",
        "riv_program_12": 44.8,
        "riv_program_14": 49.6,
        "riv_program_15": 42.8,
        "riv_program_18": 0,
        "riv_program_23": "ENA",
        "riv_program_24": "ENA",
        "riv_program_25": "ENA",
        "riv_program_26": "ENA",
        "riv_program_27": "ENA",
        "riv_program_35": 50.4,
        "riv_program_36": 80.0,
        "riv_program_37": 50.8,
        "riv_program_38": 120.0,
        "riv_operating_state": "Inverter",
        "riv_fault_count": 0,
        "riv_active_faults": "None",
        "riv_warning_mask": 50,
        "riv_warning_bits_set": "1, 4, 5",
        "riv_active_warnings": "Unverified (0x0032)",
        "riv_warning_definition_status": "unverified_for_model",
        "riv_research_word_0014": 403,
        "riv_research_word_0015": 107,
        "riv_research_word_10df": "300*107*160*403",
        "riv_diagnostic_read_status": "complete",
    }
    assert all(result[key] == value for key, value in expected.items())
    assert target.parsed_data == {"battery_voltage": 50.6}
    requests = [
        (int.from_bytes(r[2:4], "big"), int.from_bytes(r[4:6], "big"))
        for r in wire.requests
    ]
    assert len(requests) == 81
    assert requests[:9] == [
        (4393, 1),
        (4398, 4),
        (4405, 1),
        (4422, 1),
        (4424, 14),
        (4439, 6),
        (4447, 1),
        (4101, 1),
        (0xE20D, 1),
    ]
    assert requests[8::9] == [
        (0xE20D, 1),
        (0xE20E, 1),
        (0xE211, 1),
        (0xE212, 1),
        (0xE001, 1),
        (0xE208, 1),
        (0x0014, 1),
        (0x0015, 1),
        (0x10DF, 8),
    ]
    fields = {
        field.key: field for field in get_inverter_diagnostic_fields(RIV4835CSH1S_MODEL)
    }
    assert len([key for key in fields if key.startswith("riv_program_")]) == 29
    assert fields["riv_program_04"].precision == 1
    assert fields["riv_program_02"].precision == 2
    assert not any(f"riv_program_{n:02d}" in fields for n in [16, 21, 28, 29, 39])
    details = result["riv_diagnostics"]["fields"]["riv_program_23"]
    assert details["read_response"]["response_hex"] == "20 03 02 00 01 C5 83"
    assert details["sampled_at"] and details["cached"]


@pytest.mark.parametrize(
    "kind,model", [("controller", RIV4835CSH1S_MODEL), ("inverter", None)]
)
def test_reject_other_profiles_before_io(wire, kind, model):
    with pytest.raises(ValueError, match="inverter profile"):
        asyncio.run(RenogyBleClient().read_inverter_diagnostics(device(kind, model)))
    assert wire.requests == []
    assert get_inverter_diagnostic_fields(None) == ()


@pytest.mark.parametrize(
    "response",
    [
        None,
        b"\x20\x03\x02\x00\x01\x00\x00",
        frame([1], device_id=1),
        frame([1], function=4),
        frame([1, 2]),
    ],
)
def test_invalid_reply_is_unavailable_not_zero(wire, response):
    wire.overrides[0xE20D] = response
    result = asyncio.run(RenogyBleClient().read_inverter_diagnostics(device()))
    assert "riv_program_23" not in result
    evidence = result["riv_diagnostics"]["fields"]["riv_program_23"]
    assert evidence["read_status"] == "read_error"
    assert evidence["raw_value"] is None and evidence["read_error"]
    assert result["riv_program_04"] == 49.2


def test_unsupported_reply_is_crc_validated_and_not_retried(wire):
    wire.overrides[0xE20D] = bytes.fromhex("20 83 02 90 FB")
    client = RenogyBleClient(transport_mode="persistent_session")
    result = asyncio.run(complete_pass(client, device()))
    evidence = result["riv_diagnostics"]["fields"]["riv_program_23"]
    assert evidence["read_status"] == "unsupported"
    assert evidence["next_read_at"] is None
    assert evidence["read_response"]["crc_validated"] is True
    assert evidence["read_response"]["exception_code"] == 2
    assert result["riv_diagnostic_read_status"] == "partial"
    assert sum(r[2:4] == b"\xe2\x0d" for r in wire.requests) == 1


def test_bad_exception_crc_is_a_retryable_failure(wire):
    wire.overrides[0xE20D] = bytes.fromhex("20 83 02 00 00")
    result = asyncio.run(RenogyBleClient().read_inverter_diagnostics(device()))
    evidence = result["riv_diagnostics"]["fields"]["riv_program_23"]
    assert evidence["read_status"] == "read_error" and evidence["next_read_at"]
    assert evidence["read_response"].get("crc_validated") is not True


def test_failed_refresh_drops_stale_setting_but_keeps_other_caches(wire):
    async def scenario():
        client = RenogyBleClient(transport_mode="persistent_session")
        target = device()
        result = await complete_pass(client, target)
        cache = result["riv_diagnostics"]
        cache["register_reads"][str(0xE20D)]["next_read_at"] = (
            "2000-01-01T00:00:00+00:00"
        )
        wire.overrides[0xE20D] = None
        return await client.read_inverter_diagnostics(target, previous=cache)

    result = asyncio.run(scenario())
    assert "riv_program_23" not in result
    assert result["riv_program_24"] == "ENA"
    assert result["riv_research_word_0014"] == 403
    assert sum(r[2:4] == b"\x00\x14" for r in wire.requests) == 1


def test_fault_codes_and_zero_warning_mask_keep_interpretation_limits(wire):
    wire.words.update({4393: 0, 4398: 18, 4399: 21})
    result = asyncio.run(RenogyBleClient().read_inverter_diagnostics(device()))
    assert result["riv_fault_count"] == 2
    assert result["riv_fault_code_1"] == 18
    assert result["riv_active_faults"] == (
        "18: Unverified for this model; 21: Fan failure"
    )
    assert result["riv_fault_decode_status"] == "mixed"
    assert result["riv_active_warnings"] == "Unverified (0x0000)"
    assert result["riv_warning_bits_set"] == "None"


def test_unsupported_sentinel_does_not_become_a_setting(wire):
    wire.words[4437] = 0xFFFF
    result = asyncio.run(RenogyBleClient().read_inverter_diagnostics(device()))
    assert "riv_program_04" not in result
    assert result["riv_program_05"] == 53.6
    assert result["riv_diagnostics"]["fields"]["riv_program_04"]["read_status"] == (
        "unsupported"
    )


@pytest.mark.parametrize(
    "words", [[0] * 8, [0xFFFF] * 8, ascii_words("ok")[:1] + [0, 0x41] + [0] * 5]
)
def test_invalid_firmware_text_has_no_display_value(wire, words):
    wire.words.update({0x10DF + i: value for i, value in enumerate(words)})
    result = asyncio.run(complete_pass(RenogyBleClient(), device()))
    assert "riv_research_word_10df" not in result
    assert result["riv_diagnostic_read_status"] == "partial"
