"""Exercise semantic writes through real serialization and acknowledgement handling."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from renogy_ble import RenogyBleClient, RenogyBLEDevice, get_device_settings, modbus_crc
from renogy_ble import ble as transport


class EchoTransport:
    def __init__(self, failure=None):
        self.is_connected = True
        self.requests = []
        self.failure = failure
        self.handler = None
        self.connect = AsyncMock(return_value=self)

    async def start_notify(self, _target, handler):
        self.handler = handler

    async def write_gatt_char(self, _target, payload):
        request = bytes(payload)
        self.requests.append(request)
        response = request
        if self.failure == "timeout":
            return
        if self.failure == "ble":
            raise transport.BleakError("connection lost")
        if self.failure == "exception":
            response = bytes([request[0], 0x86, 2])
            response += bytes(modbus_crc(response))
        if self.failure == "exception_crc":
            response = bytes([request[0], 0x86, 2, 0, 0])
        if self.failure == "crc":
            response = request[:-1] + bytes([request[-1] ^ 0xFF])
        if self.failure == "mismatch":
            response = request[:5] + bytes([request[5] ^ 1])
            response += bytes(modbus_crc(response))
        # Exercise buffering in the real notification and response handlers.
        assert self.handler is not None
        self.handler(None, response[:3])
        self.handler(None, response[3:])

    async def read_gatt_char(self, _target):
        return b"\x00"

    async def stop_notify(self, _target):
        pass

    async def disconnect(self):
        self.is_connected = False


def device(kind, name="BT-TH-test", model=None):
    ble_device = MagicMock(address="AA:BB:CC:DD:EE:FF")
    ble_device.name = name
    return RenogyBLEDevice(
        ble_device,
        device_type=kind,
        model_hint=model,
        advertisement_name=name,
    )


@pytest.fixture
def echo(monkeypatch):
    fake = EchoTransport()
    monkeypatch.setattr(transport, "establish_connection", fake.connect)
    monkeypatch.setattr(transport, "INVERTER_INIT_DELAY", 0)
    return fake


# Independent expectations from the existing writable controls, not calculated
# from the candidate metadata. Include decimal values vulnerable to float truncation.
DCC_WRITES = [
    ("battery_type", "custom", 0xE004, 0),
    ("battery_type", "open", 0xE004, 1),
    ("battery_type", "sealed", 0xE004, 2),
    ("battery_type", "gel", 0xE004, 3),
    ("battery_type", "lithium", 0xE004, 4),
    ("max_charging_current", 40, 0xE001, 4000),
    ("overvoltage_threshold", 14.3, 0xE005, 143),
    ("charging_limit_voltage", 14.4, 0xE006, 144),
    ("equalization_voltage", 14.6, 0xE007, 146),
    ("boost_voltage", 14.4, 0xE008, 144),
    ("float_voltage", 13.8, 0xE009, 138),
    ("boost_return_voltage", 13.2, 0xE00A, 132),
    ("overdischarge_return_voltage", 12.6, 0xE00B, 126),
    ("undervoltage_warning", 12.1, 0xE00C, 121),
    ("overdischarge_voltage", 11.7, 0xE00D, 117),
    ("discharge_limit_voltage", 10.5, 0xE00E, 105),
    ("overdischarge_delay", 30, 0xE010, 30),
    ("equalization_time", 120, 0xE011, 120),
    ("boost_time", 120, 0xE012, 120),
    ("equalization_interval", 30, 0xE013, 30),
    ("temperature_compensation", 3, 0xE014, 3),
    ("reverse_charging_voltage", 13.7, 0xE020, 137),
    ("solar_cutoff_current", 7.53, 0xE038, 753),
]


@pytest.mark.parametrize("key,value,register,wire", DCC_WRITES)
def test_dcc_serialized_write(echo, key, value, register, wire):
    result = asyncio.run(RenogyBleClient().write_setting(device("dcc"), key, value))
    expected = bytes([0xFF, 6]) + register.to_bytes(2, "big") + wire.to_bytes(2, "big")
    assert result.success and result.error is None
    assert echo.requests == [expected + bytes(modbus_crc(expected))]
    assert not echo.is_connected


@pytest.mark.parametrize(
    "native,wire",
    [("custom", 5), ("open", 1), ("sealed", 2), ("gel", 3), ("lithium", 4)],
)
def test_controller_enum(echo, native, wire):
    assert asyncio.run(
        RenogyBleClient().write_setting(device("controller"), "battery_type", native)
    ).success
    assert echo.requests[0][:6] == bytes([0xFF, 6, 0xE0, 4, 0, wire])


@pytest.mark.parametrize("state,wire", [(True, 1), (False, 0)])
def test_load_boolean(echo, state, wire):
    assert asyncio.run(
        RenogyBleClient().write_setting(device("controller"), "load_enabled", state)
    ).success
    assert echo.requests[0][:6] == bytes([0xFF, 6, 1, 10, 0, wire])


@pytest.mark.parametrize(
    "key,value,register,wire",
    [
        ("inverter_ac_input_current_limit", 50, 0x1168, 500),
        ("inverter_charge_current", 150, 0x1146, 1500),
        ("inverter_low_voltage_warn", 12.3, 0x114E, 123),
        ("inverter_over_voltage", 14.3, 0x1164, 143),
        ("inverter_ac_charge_current", 10, 0xE205, 100),
    ],
)
def test_inverter_serialized_write(echo, key, value, register, wire):
    model = "RIV4835CSH1S" if key == "inverter_ac_charge_current" else None
    target = device("inverter", "BTRIC-test", model)
    assert asyncio.run(RenogyBleClient().write_setting(target, key, value)).success
    assert echo.requests[-1][:6] == bytes([0x20, 6]) + register.to_bytes(
        2, "big"
    ) + wire.to_bytes(2, "big")


@pytest.mark.parametrize("explicit", [None, 0xFF, 0x30])
def test_low_level_inverter_default_and_explicit_addresses(echo, explicit):
    client = RenogyBleClient(device_id=explicit)
    assert asyncio.run(
        client.write_single_register(device("inverter"), 0xE205, 50)
    ).success
    assert echo.requests[-1][0] == (0x20 if explicit is None else explicit)


@pytest.mark.parametrize(
    "kind,name,model,key,value",
    [
        ("battery", "RBT-test", None, "battery_type", "custom"),
        ("shunt300", "SHUNT300", None, "load_enabled", True),
        ("hub", "HUB", None, "load_enabled", True),
        ("controller", "BT-TH-test", None, "boost_voltage", 14.4),
        ("controller", "BT-TH-test", None, "max_charging_current", 40),
        ("dcc", "BT-TH-test", None, "load_enabled", True),
        ("inverter", "RNGRIU-test", None, "inverter_charge_current", 10),
        ("inverter", "BTRIC-test", "unknown", "inverter_charge_current", 10),
        ("inverter", "BTRIC-test", "RIV4835CSH1S", "inverter_charge_current", 10),
        ("inverter", "BTRIC-test", None, "inverter_ac_charge_current", 10),
    ],
)
def test_unsupported_profile_setting_has_no_transport(
    echo, kind, name, model, key, value
):
    result = asyncio.run(
        RenogyBleClient().write_setting(device(kind, name, model), key, value)
    )
    assert not result.success and isinstance(result.error, ValueError)
    assert not echo.requests
    echo.connect.assert_not_awaited()


@pytest.mark.parametrize(
    "kind,key,value,model",
    [
        ("dcc", "boost_voltage", 17.1, None),
        ("dcc", "boost_voltage", 6.9, None),
        ("dcc", "boost_voltage", 14.31, None),
        ("dcc", "boost_voltage", float("nan"), None),
        ("dcc", "boost_voltage", float("inf"), None),
        ("dcc", "boost_voltage", True, None),
        ("dcc", "boost_voltage", "14.4", None),
        ("dcc", "solar_cutoff_current", 7.531, None),
        ("dcc", "max_charging_current", 25, None),
        ("dcc", "battery_type", 0, None),
        ("dcc", "battery_type", "invalid", None),
        ("controller", "load_enabled", 1, None),
        ("inverter", "inverter_ac_charge_current", 2.5, "RIV4835CSH1S"),
        ("inverter", "inverter_ac_charge_current", 45, "RIV4835CSH1S"),
    ],
)
def test_invalid_native_value_has_no_transport(echo, kind, key, value, model):
    result = asyncio.run(
        RenogyBleClient().write_setting(device(kind, model=model), key, value)
    )
    assert not result.success and isinstance(result.error, ValueError)
    echo.connect.assert_not_awaited()


@pytest.mark.parametrize(
    "failure", ["timeout", "exception", "exception_crc", "crc", "mismatch", "ble"]
)
def test_transaction_failure_is_not_success(echo, failure):
    echo.failure = failure
    client = RenogyBleClient(max_notification_wait_time=0.01)
    result = asyncio.run(client.write_setting(device("dcc"), "battery_type", "custom"))
    assert not result.success and result.error is not None
    assert not echo.is_connected


def test_explicit_inverter_exception_uses_request_address(echo):
    echo.failure = "exception"
    result = asyncio.run(
        RenogyBleClient(device_id=0x30).write_setting(
            device("inverter", model="RIV4835CSH1S"), "inverter_ac_charge_current", 5
        )
    )
    assert not result.success
    assert "Modbus exception code 2" in str(result.error)


def test_capabilities_are_explicit_and_have_no_wire_metadata():
    assert len(get_device_settings("dcc")) == 19
    assert {cap.key for cap in get_device_settings("controller")} == {
        "battery_type",
        "load_enabled",
    }
    assert not get_device_settings("inverter")
    assert not get_device_settings("hub")
    for cap in get_device_settings("dcc"):
        assert not hasattr(cap, "register") and not hasattr(cap, "scale")
