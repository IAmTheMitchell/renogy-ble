"""Semantic capabilities for the existing writable device settings.

The explicit allowlists preserve supported writes; a readable field alone never
confers write support. Bounds inherited from the integration are conservative
application limits, not a claim of hardware validation for every model.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from .identification import RENOGY_REGO_INVERTER_PREFIX, RIV4835CSH1S_MODEL
from .register_map import REGISTER_MAP

SettingValue = str | float | int | bool


@dataclass(frozen=True)
class DeviceSetting:
    """A semantic capability with native units and no wire metadata."""

    key: str
    kind: Literal["number", "choice", "boolean"]
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    options: tuple[str | int, ...] = ()


@dataclass(frozen=True)
class _SettingSpec:
    capability: DeviceSetting
    register: int
    quantum: Decimal = Decimal(1)
    enum: tuple[tuple[int, str], ...] = ()

    def encode(self, value: SettingValue) -> int:
        """Reject lossy conversions before any device transaction."""
        cap = self.capability
        if cap.kind == "boolean":
            if not isinstance(value, bool):
                raise ValueError(f"{cap.key} requires a boolean")
            return int(value)
        if self.enum:
            for code, option in self.enum:
                if isinstance(value, str) and value == option:
                    return code
            raise ValueError(f"Unsupported {cap.key}: {value!r}")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{cap.key} requires a native numeric value")
        native = Decimal(str(value))
        if not native.is_finite():
            raise ValueError(f"{cap.key} requires a finite value")
        if cap.minimum is not None and native < Decimal(str(cap.minimum)):
            raise ValueError(f"{cap.key} is below {cap.minimum}")
        if cap.maximum is not None and native > Decimal(str(cap.maximum)):
            raise ValueError(f"{cap.key} is above {cap.maximum}")
        if cap.options and value not in cap.options:
            raise ValueError(f"Unsupported {cap.key}: {value!r}")
        if cap.step is not None:
            origin = Decimal(str(cap.minimum or 0))
            if (native - origin) % Decimal(str(cap.step)):
                raise ValueError(f"{cap.key} requires steps of {cap.step}")
        wire = native / self.quantum
        if wire != wire.to_integral_value() or not 0 <= wire <= 65535:
            raise ValueError(f"{cap.key} cannot be represented by the device")
        return int(wire)


def _mapped_spec(profile: str, cap: DeviceSetting) -> _SettingSpec:
    """Share enums, precision and field offsets with the existing read parser."""
    field = REGISTER_MAP[profile][cap.key]
    # A block response begins with a three-byte Modbus header. Each word after
    # that advances the target register by one, including packed first words.
    register = field["register"] + (field["offset"] - 3) // 2
    return _SettingSpec(
        cap,
        register,
        Decimal(str(field.get("scale", 1))),
        tuple(field.get("map", {}).items()),
    )


_BATTERY_TYPE = DeviceSetting(
    "battery_type", "choice", options=("custom", "open", "sealed", "gel", "lithium")
)
_DCC_NUMBERS = (
    DeviceSetting("overvoltage_threshold", "number", 7.0, 17.0, 0.1),
    DeviceSetting("charging_limit_voltage", "number", 7.0, 17.0, 0.1),
    DeviceSetting("equalization_voltage", "number", 7.0, 17.0, 0.1),
    DeviceSetting("boost_voltage", "number", 7.0, 17.0, 0.1),
    DeviceSetting("float_voltage", "number", 7.0, 17.0, 0.1),
    DeviceSetting("boost_return_voltage", "number", 7.0, 17.0, 0.1),
    DeviceSetting("overdischarge_return_voltage", "number", 7.0, 17.0, 0.1),
    DeviceSetting("undervoltage_warning", "number", 7.0, 17.0, 0.1),
    DeviceSetting("overdischarge_voltage", "number", 7.0, 17.0, 0.1),
    DeviceSetting("discharge_limit_voltage", "number", 7.0, 17.0, 0.1),
    DeviceSetting("reverse_charging_voltage", "number", 11.0, 15.0, 0.1),
    DeviceSetting("overdischarge_delay", "number", 0, 120, 1),
    DeviceSetting("equalization_time", "number", 0, 300, 1),
    DeviceSetting("boost_time", "number", 10, 300, 1),
    DeviceSetting("equalization_interval", "number", 0, 255, 1),
    DeviceSetting("temperature_compensation", "number", 0, 5, 1),
    DeviceSetting("solar_cutoff_current", "number", 0, 10, 0.01),
)
_DCC_SPECS = tuple(
    _mapped_spec("dcc", cap)
    for cap in (
        _BATTERY_TYPE,
        DeviceSetting(
            "max_charging_current", "choice", options=(10, 20, 30, 40, 50, 60)
        ),
        *_DCC_NUMBERS,
    )
)
_CONTROLLER_SPECS = (
    _mapped_spec("controller", _BATTERY_TYPE),
    _SettingSpec(DeviceSetting("load_enabled", "boolean"), 0x010A),
)
# REGO and RIV setpoints are also used by the inverter read profile.
_INVERTER_SPECS = (
    _SettingSpec(
        DeviceSetting("inverter_ac_input_current_limit", "number", 1.0, 50.0, 1.0),
        4456,
        Decimal("0.1"),
    ),
    _SettingSpec(
        DeviceSetting("inverter_charge_current", "number", 5.0, 150.0, 5.0),
        4422,
        Decimal("0.1"),
    ),
    _SettingSpec(
        DeviceSetting("inverter_low_voltage_warn", "number", 9.0, 15.5, 0.1),
        4430,
        Decimal("0.1"),
    ),
    _SettingSpec(
        DeviceSetting("inverter_over_voltage", "number", 9.0, 16.0, 0.1),
        4452,
        Decimal("0.1"),
    ),
    _SettingSpec(
        DeviceSetting("inverter_ac_charge_current", "number", 0.0, 40.0, 5.0),
        57861,
        Decimal("0.1"),
    ),
)


def _setting_specs(
    device_type: str, *, model_hint: str | None = None, advertisement_name: str = ""
) -> tuple[_SettingSpec, ...]:
    if device_type == "dcc":
        return _DCC_SPECS
    if device_type == "controller":
        return _CONTROLLER_SPECS
    if device_type == "inverter":
        if model_hint == RIV4835CSH1S_MODEL:
            return _INVERTER_SPECS[-1:]
        if model_hint is None and advertisement_name.startswith(
            RENOGY_REGO_INVERTER_PREFIX
        ):
            return _INVERTER_SPECS[:-1]
    return ()


def get_device_settings(
    device_type: str, *, model_hint: str | None = None, advertisement_name: str = ""
) -> tuple[DeviceSetting, ...]:
    """Return supported settings for an explicitly selected device/profile.

    Unknown inverter profiles, batteries, Shunts and Communication Hubs have no
    semantic write capabilities. REGO retains its established BTRIC name gate.
    """
    return tuple(
        spec.capability
        for spec in _setting_specs(
            device_type, model_hint=model_hint, advertisement_name=advertisement_name
        )
    )


def _inverter_setting(key: str) -> _SettingSpec:
    return next(spec for spec in _INVERTER_SPECS if spec.capability.key == key)
