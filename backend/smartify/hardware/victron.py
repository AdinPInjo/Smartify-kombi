"""Decode Victron "Instant Readout" Bluetooth advertisements with ``victron-ble``.

Victron devices broadcast their live values every second or so, encrypted with
a per-device key. Reading them is passive: nothing is ever sent to the device.
"""

from __future__ import annotations

import enum
import inspect

from smartify.hardware.base import HardwareError, VictronReading

VICTRON_MANUFACTURER_ID = 0x02E1
INSTANT_READOUT_PREFIX = 0x10

# victron-ble parser module -> our device kind
_KINDS = {
    "battery_monitor": "battery_monitor",  # SmartShunt, BMV-712
    "solar_charger": "solar_charger",  # SmartSolar MPPT
    "dcdc_converter": "dcdc_converter",  # Orion-Tr Smart
    "orion_xs": "dcdc_converter",  # Orion XS
    "vebus": "inverter_charger",  # MultiPlus/Quattro via VE.Bus Smart dongle
}


def is_instant_readout(data: bytes) -> bool:
    return len(data) > 8 and data[0] == INSTANT_READOUT_PREFIX


def _plain(value: object) -> float | int | str | None:
    if isinstance(value, enum.Enum):
        return value.name.lower()
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int | float):
        return round(value, 3) if isinstance(value, float) else value
    return str(value)


def decode(device: str, key: str, data: bytes, rssi: int | None = None) -> VictronReading:
    """Decrypt and decode one advertisement. Raises ``HardwareError`` if it can't."""
    try:
        from victron_ble.devices import detect_device_type
        from victron_ble.exceptions import AdvertisementKeyMismatchError
    except ImportError as exc:  # pragma: no cover - depends on the install
        raise HardwareError(
            "Victron support needs the 'pi' extras: pip install 'smartify-kombi[pi]'"
        ) from exc

    parser_class = detect_device_type(data)
    if parser_class is None:
        raise HardwareError(f"{device}: unsupported Victron device type")
    try:
        parsed = parser_class(key).parse(data)
    except AdvertisementKeyMismatchError as exc:
        raise HardwareError(f"{device}: wrong encryption key") from exc
    except Exception as exc:
        raise HardwareError(f"{device}: could not decode advertisement: {exc}") from exc

    module = parser_class.__module__.rsplit(".", 1)[-1]
    values: dict[str, float | int | str | None] = {}
    model = None
    for name, method in inspect.getmembers(parsed, predicate=inspect.ismethod):
        if not name.startswith("get_"):
            continue
        if name == "get_model_name":
            model = method()
            continue
        try:
            values[name[4:]] = _plain(method())
        except Exception:  # one odd field must not drop the whole reading
            values[name[4:]] = None
    return VictronReading(device, _KINDS.get(module, module), model, values, rssi)
