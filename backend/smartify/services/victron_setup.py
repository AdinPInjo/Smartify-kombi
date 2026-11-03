"""Victron devices added from the dashboard.

Devices come from two places: the dashboard (``victron_devices`` table) and,
for older installs, ``SMARTIFY_VICTRON_DEVICES`` in ``.env``. Both are read
the same way; only dashboard devices can be removed from the dashboard.

Adding a device checks the encryption key against the device's latest
Bluetooth advertisement when it has been heard, so a typo in the key is
caught right away instead of showing up later as "no data".
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from smartify.config import VictronDevice
from smartify.db import transaction
from smartify.errors import Conflict, InvalidInput, NotFound
from smartify.hardware import VictronListener

log = logging.getLogger(__name__)

_NAME = re.compile(r"^[a-z0-9_-]{1,32}$")
_MAC = re.compile(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$")
_KEY = re.compile(r"^[0-9a-f]{32}$")

KIND_NAMES = {
    "battery_monitor": "shunt",
    "solar_charger": "solar",
    "dcdc_converter": "orion",
    "inverter_charger": "multiplus",
}


def normalize_mac(value: str) -> str:
    """``aabbccddeeff``, ``aa-bb-...`` or ``AA:BB:...`` -> ``AA:BB:CC:DD:EE:FF``."""
    digits = re.sub(r"[^0-9A-Fa-f]", "", value).upper()
    if len(digits) != 12:
        raise InvalidInput("the MAC address has 12 hex digits, like AA:BB:CC:DD:EE:FF")
    return ":".join(digits[i : i + 2] for i in range(0, 12, 2))


def normalize_key(value: str) -> str:
    key = re.sub(r"\s", "", value).lower()
    if not _KEY.match(key):
        raise InvalidInput(
            "the encryption key has 32 characters (0-9 and a-f); copy it from VictronConnect"
        )
    return key


@dataclass(frozen=True)
class ConfiguredDevice:
    name: str
    mac: str
    source: str
    """'dashboard' or 'env' (from .env, can only be changed there)."""


class VictronDevices:
    def __init__(
        self,
        db_path: Path,
        env_devices: list[VictronDevice],
        listener: VictronListener | None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._db_path = db_path
        self._env = list(env_devices)
        self._listener = listener
        self._clock = clock

    @property
    def available(self) -> bool:
        """Bluetooth support present (the listener could be created)."""
        return self._listener is not None

    @property
    def error(self) -> str | None:
        if self._listener is None:
            return "Bluetooth support is not installed"
        return getattr(self._listener, "error", None)

    def _stored(self) -> list[VictronDevice]:
        with transaction(self._db_path) as conn:
            rows = conn.execute(
                "SELECT name, mac, key FROM victron_devices ORDER BY name"
            ).fetchall()
        return [VictronDevice(name=r["name"], mac=r["mac"], key=r["key"]) for r in rows]

    def all(self) -> list[VictronDevice]:
        """Every device to read: .env first, then dashboard ones (a name/MAC in .env wins)."""
        devices = list(self._env)
        names = {d.name for d in devices}
        macs = {d.mac.upper() for d in devices}
        for device in self._stored():
            if device.name not in names and device.mac.upper() not in macs:
                devices.append(device)
        return devices

    def configured(self) -> list[ConfiguredDevice]:
        env_names = {d.name for d in self._env}
        return [
            ConfiguredDevice(d.name, d.mac.upper(), "env" if d.name in env_names else "dashboard")
            for d in self.all()
        ]

    def names(self) -> list[str]:
        return [d.name for d in self.all()]

    def apply(self) -> None:
        """Hand the current device list to the Bluetooth listener."""
        if self._listener is not None:
            self._listener.set_devices(self.all())

    def discovered(self) -> list[dict[str, Any]]:
        """Victron devices nearby, marking the ones already added."""
        if self._listener is None:
            return []
        by_mac = {d.mac.upper(): d.name for d in self.all()}
        return [
            {
                **asdict(device),
                "added_as": by_mac.get(device.mac.upper()),
                "suggested_name": self.suggest_name(device.kind),
            }
            for device in self._listener.discovered()
        ]

    def suggest_name(self, kind: str | None) -> str:
        base = KIND_NAMES.get(kind or "", "victron")
        taken = set(self.names())
        if base not in taken:
            return base
        number = 2
        while f"{base}{number}" in taken:
            number += 1
        return f"{base}{number}"

    def add(self, name: str, mac: str, key: str) -> dict[str, Any]:
        name = name.strip().lower()
        if not _NAME.match(name):
            raise InvalidInput("the name may use a-z, 0-9, - and _ (up to 32), e.g. shunt")
        mac, key = normalize_mac(mac), normalize_key(key)
        if not _MAC.match(mac):
            raise InvalidInput("invalid MAC address")
        for device in self.all():
            if device.name == name:
                raise Conflict(f"a device called {name} already exists")
            if device.mac.upper() == mac:
                raise Conflict(f"this device is already added as {device.name}")

        heard = self._listener.check_key(mac, key) if self._listener else None
        if heard is False:
            raise InvalidInput(
                "this key does not match the device. In VictronConnect open the device, "
                "then ⚙ › Product info › Instant readout details › Show, and copy the key again"
            )
        with transaction(self._db_path) as conn:
            conn.execute(
                "INSERT INTO victron_devices (name, mac, key, created_at) VALUES (?, ?, ?, ?)",
                (name, mac, key, int(self._clock())),
            )
        self.apply()
        log.info("Victron device %s (%s) added from the dashboard", name, mac)
        return {"name": name, "mac": mac, "key_checked": heard is True}

    def remove(self, name: str) -> None:
        if name in {d.name for d in self._env}:
            raise Conflict(f"{name} is set in .env (SMARTIFY_VICTRON_DEVICES); remove it there")
        with transaction(self._db_path) as conn:
            deleted = conn.execute("DELETE FROM victron_devices WHERE name = ?", (name,)).rowcount
        if not deleted:
            raise NotFound(f"Victron device {name} not found")
        self.apply()
        log.info("Victron device %s removed", name)
