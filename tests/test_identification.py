"""Shared identification and protocol-consumer regression coverage."""

import asyncio

import pytest
from bleak.backends.device import BLEDevice

from renogy_ble import (
    DeviceType,
    RenogyBleClient,
    RenogyBLEDevice,
    detect_battery_variant,
    detect_device_type_from_model,
    get_device_settings,
    identify_advertisement,
    is_address_placeholder,
    is_supported_battery_name,
    name_matches_device_type,
)
from renogy_ble.battery import BATTERY_PRO_MANUFACTURER_ID
from tests.test_battery_rngpro import CELL_STATUS, MOSFET_STATUS, PACK_STATUS


@pytest.mark.parametrize(
    "name,device_type,variant",
    [
        ("BT-TH-123", None, None),
        ("BT-TH-BATT01", DeviceType.BATTERY, "legacy"),
        ("BT-TH-battery01", DeviceType.BATTERY, "legacy"),
        ("RNGRBP123", DeviceType.BATTERY, "pro"),
        ("RNGC123", DeviceType.BATTERY, "pro"),
        ("RNGPRO125BAT-123", DeviceType.BATTERY, "rngpro"),
        ("RNGRIU123", DeviceType.INVERTER, None),
        ("BTRIC123", DeviceType.INVERTER, None),
        ("RTMShunt300123", DeviceType.SHUNT300, None),
    ],
)
def test_supported_families(name, device_type, variant):
    identity = identify_advertisement(name)
    assert identity.supported
    assert identity.device_type == device_type
    assert identity.battery_variant == variant
    assert detect_battery_variant(name) == variant
    assert is_supported_battery_name(name) == (variant is not None)
    if device_type:
        assert name_matches_device_type(name, device_type.value)


@pytest.mark.parametrize(
    "name",
    [None, "", " ", "Unknown Renogy Device", "Other", "RBT12500LFP-SHBT", "btric123"],
)
def test_unknown_or_hardware_display_names(name):
    identity = identify_advertisement(name)
    assert not identity.supported
    assert identity.device_type is None
    assert identity.battery_variant is None
    assert detect_battery_variant(name) is None


@pytest.mark.parametrize(
    "name", [None, "", "Other", "BT-TH-123", "Unknown Renogy Device"]
)
def test_manufacturer_only_identifies_pro(name):
    manufacturer = {BATTERY_PRO_MANUFACTURER_ID: b""}
    identity = identify_advertisement(name, manufacturer_data=manufacturer)
    assert identity.supported
    assert identity.device_type == DeviceType.BATTERY
    assert identity.battery_variant == "pro"
    assert detect_battery_variant(name, manufacturer_data=manufacturer) == "pro"


@pytest.mark.parametrize(
    "name,device_type,variant",
    [
        ("RNGRIU123", DeviceType.INVERTER, None),
        ("BTRIC123", DeviceType.INVERTER, None),
        ("RTMShunt300123", DeviceType.SHUNT300, None),
        ("RNGPRO123", DeviceType.BATTERY, "rngpro"),
        ("BT-TH-BATT01", DeviceType.BATTERY, "pro"),
    ],
)
def test_conflicting_evidence_has_one_precedence(name, device_type, variant):
    manufacturer = {BATTERY_PRO_MANUFACTURER_ID: b""}
    identity = identify_advertisement(name, manufacturer_data=manufacturer)
    assert identity.device_type == device_type
    assert identity.battery_variant == variant
    assert detect_battery_variant(name, manufacturer_data=manufacturer) == variant


@pytest.mark.parametrize(
    "name,address",
    [
        ("AA:BB:CC:DD:EE:FF", "AA:BB:CC:DD:EE:FF"),
        (" aa-bb-cc-dd-ee-ff ", "AA:BB:CC:DD:EE:FF"),
        (
            "B9EA5233-37EF-4DD6-87A8-2A875E821C46",
            "B9EA5233-37EF-4DD6-87A8-2A875E821C46",
        ),
        ("RNGPRO123", "RNGPRO123"),
    ],
)
def test_own_address_is_never_a_name(name, address):
    assert is_address_placeholder(name, address)
    assert not identify_advertisement(name, address=address).supported
    assert detect_battery_variant(name, address=address) is None
    assert not name_matches_device_type(name, "battery", address=address)
    assert (
        identify_advertisement(
            name, address=address, manufacturer_data={0xE14C: b""}
        ).battery_variant
        == "pro"
    )


@pytest.mark.parametrize("selected_type", ["controller", "dcc", "battery"])
def test_generic_bt_th_preserves_selected_protocol(selected_type):
    name = "BT-TH-123"
    assert identify_advertisement(name).device_type is None
    assert name_matches_device_type(name, selected_type)
    device = RenogyBLEDevice(BLEDevice("other", name, {}), device_type=selected_type)
    assert device.device_type == selected_type
    assert device.battery_variant is None


@pytest.mark.parametrize(
    "model", ["DCC30S", "DCC50S", "RBC20D1U", "RBC50D1S-G6", " rbc30d1s "]
)
def test_dcc_model_classification(model):
    assert detect_device_type_from_model(model) == "dcc"


@pytest.mark.parametrize(
    "model",
    [None, "", " ", "RNG-CTRL-RVR40", "RBT100LFP12S", "RBC1218S0", "RIV4835CSH1S"],
)
def test_other_models_do_not_suggest_reconfiguration(model):
    assert detect_device_type_from_model(model) is None


def test_settings_retain_explicit_profile_over_name():
    assert len(get_device_settings("inverter", advertisement_name="BTRIC123")) == 4
    settings = get_device_settings(
        "inverter", model_hint="RIV4835CSH1S", advertisement_name="BTRIC123"
    )
    assert [setting.key for setting in settings] == ["inverter_ac_charge_current"]
    assert (
        get_device_settings(
            "inverter", model_hint="other", advertisement_name="BTRIC123"
        )
        == ()
    )


def test_later_rngpro_advertisement_refines_pro_before_real_read(monkeypatch):
    """Exercise transport and captured frames after provisional Pro discovery."""
    from renogy_ble import ble as module

    class Client:
        is_connected = True

        async def start_notify(self, _target, callback):
            self.callback = callback

        async def write_gatt_char(self, _target, payload, response=None):
            register = int.from_bytes(payload[2:4], "big")
            frames = {
                0x13F0: bytes([0xFF, 0x03, 56]) + bytes(58),
                0x13B2: PACK_STATUS,
                0x1388: CELL_STATUS,
                0x13EC: MOSFET_STATUS,
            }
            if register in frames:
                frame = frames[register][:-2]
                self.callback(None, frame + bytes(module.modbus_crc(frame)))

        async def stop_notify(self, _target):
            pass

        async def disconnect(self):
            pass

    async def connect(*args, **kwargs):
        return Client()

    monkeypatch.setattr(module, "establish_connection", connect)
    device = RenogyBLEDevice(
        BLEDevice("AA:BB:CC:DD:EE:FF", "House battery", {}),
        device_type="battery",
        manufacturer_data={0xE14C: b""},
    )
    assert device.battery_variant == "pro"
    device.advertised_name = "RNGPRO125BAT-EF036881"
    result = asyncio.run(
        RenogyBleClient(max_notification_wait_time=0.01).read_device(device)
    )
    assert result.success
    assert device.battery_variant == "rngpro"
    assert result.parsed_data["battery_current"] == -2.01
    assert result.parsed_data["cell_voltages"] == [3.3] * 4
    assert "battery_problem_code" not in result.parsed_data
    assert device.device_type == "battery"


def test_address_shape_alone_does_not_reject_a_name():
    assert not is_address_placeholder("14:9C:EF:03:68:81", "AA:BB:CC:DD:EE:FF")
    assert not is_address_placeholder("14:9C:EF", None)


def test_missing_packet_has_no_guess_or_state():
    assert identify_advertisement(None, manufacturer_data={0xE14C: b""}).supported
    assert not identify_advertisement(None, manufacturer_data={}).supported


@pytest.mark.parametrize(
    "name,identified_type",
    [
        ("BT-TH-BATT01", DeviceType.BATTERY),
        (" BT-TH-battery01 ", DeviceType.BATTERY),
        ("RNGRBP123", DeviceType.BATTERY),
        ("RNGC123", DeviceType.BATTERY),
        ("RNGPRO123", DeviceType.BATTERY),
        ("RNGRIU123", DeviceType.INVERTER),
        ("BTRIC123", DeviceType.INVERTER),
        ("RTMShunt300123", DeviceType.SHUNT300),
    ],
)
@pytest.mark.parametrize("selected_type", list(DeviceType))
def test_identified_names_match_only_their_protocol(
    name, identified_type, selected_type
):
    assert name_matches_device_type(name, selected_type.value) == (
        selected_type is identified_type
    )
