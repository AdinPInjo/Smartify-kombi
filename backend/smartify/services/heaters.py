"""Diesel heaters: added in the dashboard, controlled over Bluetooth.

Switching off always sends the heater its own "off" command, so it runs its
cool-down (the fan keeps going until the burner is cold). Smartify never cuts a
heater's power: that can damage the glow plug and leave the burner hot.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from smartify.db import transaction
from smartify.errors import Conflict, DeviceUnavailable, InvalidInput, NotFound
from smartify.hardware import heater_protocol as hp
from smartify.hardware.base import HardwareError, HeaterBackend, HeaterConfig
from smartify.services.victron_setup import normalize_mac

log = logging.getLogger(__name__)

PHASE_NAMES = {
    "standby": "Off",
    "self_test": "Self-test",
    "ignition": "Igniting",
    "running": "Heating",
    "cooldown": "Cooling down",
    "ventilation": "Fan only",
    "fault": "Fault",
}


class HeaterService:
    def __init__(
        self, db_path: Path, backend: HeaterBackend | None, clock: Callable[[], float] = time.time
    ):
        self._db = db_path
        self._backend = backend
        self._clock = clock

    @property
    def available(self) -> bool:
        return self._backend is not None

    def configs(self) -> list[HeaterConfig]:
        with transaction(self._db) as conn:
            rows = conn.execute(
                "SELECT id, name, mac, pin FROM heaters ORDER BY created_at"
            ).fetchall()
        return [HeaterConfig(r["id"], r["name"], r["mac"], r["pin"]) for r in rows]

    def apply(self) -> None:
        """Tell the Bluetooth side which heaters to keep connected."""
        if self._backend is not None:
            self._backend.set_heaters(self.configs())

    def _config(self, heater_id: str) -> HeaterConfig:
        for config in self.configs():
            if config.id == heater_id:
                return config
        raise NotFound(f"heater {heater_id} not found")

    # --- what the dashboard shows --------------------------------------------------------

    def view(self, config: HeaterConfig) -> dict[str, Any]:
        link = self._backend.link(config.id) if self._backend else None
        status = asdict(link.status) if link and link.status else None
        if status:
            status["phase_name"] = PHASE_NAMES.get(status["phase"], status["phase"])
        return {
            "id": config.id,
            "name": config.name,
            "mac": config.mac,
            "connected": bool(link and link.connected),
            "error": link.error if link else "Bluetooth is not available",
            "last_seen": link.last_seen if link else None,
            "status": status,
        }

    def list(self) -> list[dict[str, Any]]:
        return [self.view(config) for config in self.configs()]

    def get(self, heater_id: str) -> dict[str, Any]:
        return self.view(self._config(heater_id))

    def nearby(self) -> list[dict[str, Any]]:
        if self._backend is None:
            return []
        added = {c.mac for c in self.configs()}
        return [{**asdict(d), "added": d.mac in added} for d in self._backend.discovered()]

    # --- setup --------------------------------------------------------------------------------

    def add(self, name: str, mac: str, pin: int = 1234) -> dict[str, Any]:
        name = name.strip()
        if not name or len(name) > 30:
            raise InvalidInput("give the heater a name of up to 30 characters")
        mac = normalize_mac(mac)
        if not 0 <= pin <= 9999:
            raise InvalidInput("the PIN has 4 digits (most heaters: 1234)")
        if any(c.mac == mac for c in self.configs()):
            raise Conflict("this heater is already added")
        heater_id = uuid.uuid4().hex[:12]
        with transaction(self._db) as conn:
            conn.execute(
                "INSERT INTO heaters (id, name, mac, pin, created_at) VALUES (?, ?, ?, ?, ?)",
                (heater_id, name, mac, pin, int(self._clock())),
            )
        self.apply()
        return self.get(heater_id)

    def update(
        self, heater_id: str, name: str | None = None, pin: int | None = None
    ) -> dict[str, Any]:
        config = self._config(heater_id)
        name = (name if name is not None else config.name).strip()
        pin = config.pin if pin is None else pin
        if not name or len(name) > 30 or not 0 <= pin <= 9999:
            raise InvalidInput("a name of up to 30 characters and a 4-digit PIN")
        with transaction(self._db) as conn:
            conn.execute(
                "UPDATE heaters SET name = ?, pin = ? WHERE id = ?", (name, pin, heater_id)
            )
        self.apply()
        return self.get(heater_id)

    def remove(self, heater_id: str) -> None:
        self._config(heater_id)
        with transaction(self._db) as conn:
            conn.execute("DELETE FROM heaters WHERE id = ?", (heater_id,))
        self.apply()

    # --- control ------------------------------------------------------------------------------

    def _send(self, heater_id: str, command: int, argument: int = 0) -> None:
        self._config(heater_id)
        if self._backend is None:
            raise DeviceUnavailable("Bluetooth is not available on this Smartify")
        try:
            self._backend.command(heater_id, command, argument)
        except HardwareError as exc:
            raise DeviceUnavailable(f"heater: {exc}") from exc

    def power(self, heater_id: str, on: bool, source: str = "dashboard") -> dict[str, Any]:
        log.info("Heater %s %s (%s)", heater_id, "on" if on else "off (cool-down)", source)
        self._send(heater_id, hp.CMD_POWER, 1 if on else 0)
        return self.get(heater_id)

    def settings(
        self,
        heater_id: str,
        mode: str | None = None,
        temperature: float | None = None,
        level: int | None = None,
    ) -> dict[str, Any]:
        try:
            if temperature is not None:
                temperature = hp.check_temperature(temperature)
            if level is not None:
                level = hp.check_level(level)
        except ValueError as exc:
            raise InvalidInput(str(exc)) from None
        if mode not in (None, "temperature", "level"):
            raise InvalidInput("mode is temperature or level")
        if mode is not None:
            self._send(
                heater_id,
                hp.CMD_MODE,
                hp.MODE_TEMPERATURE if mode == "temperature" else hp.MODE_LEVEL,
            )
        if temperature is not None:
            self._send(heater_id, hp.CMD_TEMPERATURE, temperature)
        if level is not None:
            self._send(heater_id, hp.CMD_LEVEL, level)
        return self.get(heater_id)

    def is_on(self, heater_id: str) -> bool | None:
        link = self._backend.link(heater_id) if self._backend else None
        return link.status.running if link and link.status else None
