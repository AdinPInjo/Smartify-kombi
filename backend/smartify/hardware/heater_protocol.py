"""Diesel heater Bluetooth protocols: recognize, read status, build commands.

The byte-level protocols come from the open-source ``diesel-heater-ble``
library (MIT, https://github.com/Spettacolo83/diesel-heater-ble), which covers
the controllers used by Vevor, BYD, HeaterCC, Sunster, Hcalory and others. How a
heater is recognized and which protocol it speaks follows the same author's
Home Assistant integration (homeassistant-diesel-heater, MIT).

This module has no Bluetooth code: ``HeaterSession`` turns the heater's
notifications into a ``HeaterStatus`` and Smartify's wishes into packets. The
Bluetooth side is ``hardware/pi/heater.py``; tests feed it bytes directly.
"""

from __future__ import annotations

import fnmatch
import time
from dataclasses import dataclass
from typing import Any, Literal

from smartify.hardware.base import HardwareError, HeaterStatus

# BLE layouts. Each controller family exposes one of these GATT services.
VEVOR_SERVICES = {
    "0000ffe0-0000-1000-8000-00805f9b34fb": "0000ffe1-0000-1000-8000-00805f9b34fb",
    "0000fff0-0000-1000-8000-00805f9b34fb": "0000fff1-0000-1000-8000-00805f9b34fb",
}
FFF0_SERVICE = "0000fff0-0000-1000-8000-00805f9b34fb"
FFF1 = "0000fff1-0000-1000-8000-00805f9b34fb"
FFF2 = "0000fff2-0000-1000-8000-00805f9b34fb"
HCALORY_MVP2_SERVICE = "0000bd39-0000-1000-8000-00805f9b34fb"
HCALORY_MVP2_WRITE = "0000bdf7-0000-1000-8000-00805f9b34fb"
HCALORY_MVP2_NOTIFY = "0000bdf8-0000-1000-8000-00805f9b34fb"

# Advertised names and manufacturer data the heater apps look for.
NAME_PATTERNS = (
    "Air Heater",
    "AirHeater*",
    "BYD-*",
    "HC-*",
    "Heater[0-9]*",
    "Hcalory*",
    "hcalory*",
    "BAC-*",
    "CRONUS*",
    "boygu*",
    "BOYGU*",
)
HEATER_MANUFACTURER_ID = 65294
HEATER_MANUFACTURER_PREFIXES = (
    b"\x06\xbd\x01",
    b"\x01\x02",
    b"\x01\x03",
    b"\x02\x02",
    b"\x02\x03",
    b"\x03\x01",
    b"\x03\x02",
    b"\x03\x03",
)
HEATER_SERVICE_HINTS = {"0000ffe0-0000-1000-8000-00805f9b34fb", HCALORY_MVP2_SERVICE}

# The commands every protocol class understands (Vevor numbering).
CMD_STATUS = 1
CMD_MODE = 2
CMD_POWER = 3
CMD_TEMPERATURE = 4
CMD_LEVEL = 5
MODE_LEVEL = 1
MODE_TEMPERATURE = 2

MIN_TEMPERATURE, MAX_TEMPERATURE = 8, 36
MIN_LEVEL, MAX_LEVEL = 1, 10

Transport = Literal["vevor", "abba", "hcalory1", "hcalory2"]

_STEPS = {
    0: "standby",
    1: "self_test",
    2: "ignition",
    3: "running",
    4: "cooldown",
    6: "ventilation",
}
_HCALORY_STATES = {
    0x00: "standby",
    0x01: "running",
    0x02: "running",
    0x03: "ventilation",
    0xFF: "fault",
}


def looks_like_heater(
    name: str | None, manufacturer: dict[int, bytes], services: list[str]
) -> bool:
    """Does an advertisement belong to a diesel heater controller?"""
    if name and any(fnmatch.fnmatchcase(name, pattern) for pattern in NAME_PATTERNS):
        return True
    data = manufacturer.get(HEATER_MANUFACTURER_ID)
    if data and any(bytes(data).startswith(prefix) for prefix in HEATER_MANUFACTURER_PREFIXES):
        return True
    return bool({s.lower() for s in services} & HEATER_SERVICE_HINTS)


def _library():
    try:
        import diesel_heater_ble as library
        from diesel_heater_ble import const
    except ImportError as exc:  # pragma: no cover - depends on the install
        raise HardwareError(
            "Diesel heater support needs the diesel-heater-ble library. "
            "Run the installer again: sudo ./deploy/install.sh"
        ) from exc
    return library, const


@dataclass(frozen=True)
class Layout:
    """Which characteristics to use, found from the heater's GATT services."""

    transport: Transport
    notify: str
    write: str


def choose_layout(
    services: dict[str, dict[str, set[str]]], name: str | None = None
) -> Layout | None:
    """Pick the characteristics from ``{service: {characteristic: properties}}``.

    Order as in the Home Assistant integration: Hcalory MVP2, then the FFF0
    service (Hcalory MVP1 or ABBA/HeaterCC, told apart by which characteristic
    notifies), then the single-characteristic Vevor/Sunster layouts.
    """
    lower = {s.lower(): {c.lower(): p for c, p in chars.items()} for s, chars in services.items()}
    if HCALORY_MVP2_SERVICE in lower:
        chars = lower[HCALORY_MVP2_SERVICE]
        if HCALORY_MVP2_NOTIFY in chars and HCALORY_MVP2_WRITE in chars:
            return Layout("hcalory2", HCALORY_MVP2_NOTIFY, HCALORY_MVP2_WRITE)
    fff0 = lower.get(FFF0_SERVICE, {})
    can_notify = lambda c: bool(fff0.get(c, set()) & {"notify", "indicate"})  # noqa: E731
    can_write = lambda c: bool(fff0.get(c, set()) & {"write", "write-without-response"})  # noqa: E731
    if FFF1 in fff0 and FFF2 in fff0:
        if can_notify(FFF1) and can_write(FFF2):
            # Hcalory MVP1 and legacy ABBA share this layout: the name tells them
            # apart, otherwise the session tries both (see HeaterSession.alternate).
            hcalory = bool(name and name.lower().startswith("hcalory"))
            return Layout("hcalory1" if hcalory else "abba", FFF1, FFF2)
        if can_write(FFF1) and can_notify(FFF2):
            return Layout("abba", FFF2, FFF1)
    for service, char in VEVOR_SERVICES.items():
        if char in lower.get(service, {}):
            return Layout("vevor", char, char)
    return None


class HeaterSession:
    """The protocol state of one heater connection."""

    def __init__(self, mac: str, pin: int, transport: Transport, clock=time.time) -> None:
        library, const = _library()
        self._const = const
        self.pin = pin
        self.transport = transport
        self._clock = clock
        self._protocols: dict[int, Any] = {
            1: library.ProtocolAA55(),
            2: library.ProtocolAA55Encrypted(),
            3: library.ProtocolAA66(),
            4: library.ProtocolAA66Encrypted(),
            5: library.ProtocolABBA(),
            6: library.ProtocolCBFF(),
            7: library.ProtocolHcalory(),
        }
        self._protocols[6].set_device_sn(mac.replace(":", "").upper())
        self._protocols[7].set_mvp_version(transport == "hcalory2")
        self._decrypt = library._decrypt_data
        self.protocol: Any = None
        if transport in ("hcalory1", "hcalory2"):
            self.protocol = self._protocols[7]
        self.status: HeaterStatus | None = None
        self.pending: list[bytes] = []
        """Packets to send next (handshakes the heater asked for)."""

    @property
    def protocol_name(self) -> str | None:
        return getattr(self.protocol, "name", None)

    def start(self) -> list[bytes]:
        """Packets to send right after connecting, before the first status request."""
        hcalory = self._protocols[7]
        if self.transport == "hcalory2" and hcalory.needs_password_handshake:
            hcalory.mark_password_sent()
            return [bytes(hcalory.build_password_handshake(self.pin))]
        return []

    # --- reading --------------------------------------------------------------------

    def _detect(self, data: bytearray, header: int) -> tuple[Any, bytearray] | None:
        if self.transport in ("hcalory1", "hcalory2") or header == 0x0002:
            if self.transport == "abba":
                self.transport = "hcalory1"  # FFF0 layout turned out to be Hcalory MVP1
                self._protocols[7].set_mvp_version(False)
            return self._protocols[7], data
        cbff = self._protocols[6]
        is_feaa = getattr(cbff, "is_feaa_frame", lambda _data: False)
        if self.protocol is cbff or header == 0xCBFF or is_feaa(data):
            return cbff, data
        if header == 0xABBA or self.transport == "abba":
            return self._protocols[5], data
        if len(data) < 17:
            return None
        if header == 0xAA55 and len(data) in (18, 20):
            return self._protocols[1], data
        if header == 0xAA66 and len(data) == 20:
            return self._protocols[3], data
        if len(data) == 48:
            decrypted = self._decrypt(data)
            inner = (decrypted[0] << 8) | decrypted[1]
            if inner == 0xAA55:
                return self._protocols[2], decrypted
            if inner == 0xAA66:
                return self._protocols[4], decrypted
        return None

    def feed(self, raw: bytes) -> HeaterStatus | None:
        """Handle one notification. Returns the new status, if it carried one."""
        data = bytearray(raw)
        if len(data) < 2:
            return None
        header = (data[0] << 8) | data[1]
        if header == 0xAA77:
            # Sunster V2.1 "locked": switch to its encrypted protocol and log in.
            cbff = self._protocols[6]
            if not cbff.v21_mode:
                cbff.set_v21_mode(True)
                self.protocol = cbff
                self.pending.append(bytes(cbff.build_handshake(self.pin)))
            return None
        if len(data) < 8:
            return None
        detected = self._detect(data, header)
        if detected is None:
            return None
        protocol, payload = detected
        parsed = protocol.parse(payload)
        if not parsed:
            return None
        self.protocol = protocol
        self.status = self._normalize(parsed)
        return self.status

    def _normalize(self, p: dict[str, Any]) -> HeaterStatus:
        const = self._const
        mode_code = p.get("running_mode")
        mode = {MODE_LEVEL: "level", MODE_TEMPERATURE: "temperature"}.get(mode_code)
        if self.protocol is self._protocols[7]:
            phase = _HCALORY_STATES.get(p.get("hcalory_device_state", -1))
        else:
            phase = _STEPS.get(p.get("running_step", -1))
        running = bool(p.get("running_state"))
        if phase is None:
            phase = "running" if running else "standby"
        error = int(p.get("error_code") or 0)
        names = {
            5: getattr(const, "ABBA_ERROR_NAMES", {}),
            7: getattr(const, "HCALORY_ERROR_NAMES", {}),
        }.get(getattr(self.protocol, "protocol_mode", 0), getattr(const, "ERROR_NAMES", {}))
        error_text = names.get(error, f"Fault code {error}") if error else None

        def number(key: str) -> float | None:
            value = p.get(key)
            return float(value) if isinstance(value, int | float) else None

        co = number("co_ppm")
        return HeaterStatus(
            running=running,
            phase=phase,
            mode=mode,
            target_temperature=number("set_temp"),
            level=int(p["set_level"]) if isinstance(p.get("set_level"), int | float) else None,
            cabin_temperature=number("cab_temperature"),
            heater_temperature=number("case_temperature"),
            voltage=number("supply_voltage"),
            error_code=error or None,
            error=error_text,
            co_ppm=co if co is not None and co >= 0 else None,
            protocol=self.protocol_name,
            updated_at=int(self._clock()),
        )

    # --- writing --------------------------------------------------------------------

    def command(self, command: int, argument: int = 0) -> bytes:
        protocol = self.protocol or (
            self._protocols[5] if self.transport == "abba" else self._protocols[1]
        )
        return bytes(protocol.build_command(command, argument, self.pin))

    def status_request(self) -> bytes:
        return self.command(CMD_STATUS, 0)

    def alternate(self) -> bool:
        """No answer yet on the shared FFF0 layout: try the other family.

        Returns True when it switched (ABBA/HeaterCC <-> Hcalory MVP1).
        """
        if self.status is not None or self.transport not in ("abba", "hcalory1"):
            return False
        self.transport = "hcalory1" if self.transport == "abba" else "abba"
        self._protocols[7].set_mvp_version(False)
        self.protocol = self._protocols[7] if self.transport == "hcalory1" else None
        return True


def check_temperature(value: float) -> int:
    temperature = round(value)
    if not MIN_TEMPERATURE <= temperature <= MAX_TEMPERATURE:
        raise ValueError(
            f"the heater's temperature range is {MIN_TEMPERATURE}-{MAX_TEMPERATURE} °C"
        )
    return temperature


def check_level(value: int) -> int:
    if not MIN_LEVEL <= value <= MAX_LEVEL:
        raise ValueError(f"the heater's power level is {MIN_LEVEL}-{MAX_LEVEL}")
    return value
