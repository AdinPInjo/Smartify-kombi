"""Sensors added in the dashboard (Sensors tab), from a catalog of known types.

Before 0.9.0 sensors were set in backend/.env. On the first start of this
version they are carried over once: DHT22 pins and GPS from .env (only values
that were really set there), the water sender if it ever delivered a reading.
After that the dashboard is the only place for sensors; .env is never edited.

A fresh install starts with no sensors at all, so a van with only a diesel heater
and Victron devices needs nothing else. In simulation (``hardware=mock``) the
demo van gets two climate sensors, GPS and a water tank.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from smartify.config import Settings
from smartify.db import transaction
from smartify.errors import Conflict, InvalidInput, NotFound
from smartify.hardware.base import SensorConfig

# --- the catalog ------------------------------------------------------------------------

CLIMATE_KINDS = {"dht22", "dht11", "ds18b20", "bme280", "sht31", "aht20"}
INPUT_KINDS = {"door", "motion"}
GPIO_KINDS = {"dht22", "dht11", "door", "motion"}
I2C_ADDRESSES = {"bme280": (0x76, 0x77), "sht31": (0x44, 0x45), "aht20": (0x38,)}
SINGLE_KINDS = {"gps", "water_tank"}
"""Kinds a van has at most one of."""
RESTART_KINDS = {"gps", "water_tank"}
"""Changes to these take effect after a restart of Smartify."""

KINDS = CLIMATE_KINDS | INPUT_KINDS | SINGLE_KINDS

# GPIO pins (BCM numbers) that are never free for sensors.
RESERVED_PINS = {
    0: "the HAT EEPROM",
    1: "the HAT EEPROM",
    2: "I2C (SDA)",
    3: "I2C (SCL)",
    14: "the GPS serial port (TX)",
    15: "the GPS serial port (RX)",
}
USABLE_PINS = [p for p in range(2, 28) if p not in RESERVED_PINS]
NAME = re.compile(r"^[a-z0-9_]{1,24}$")
ROM_ID = re.compile(r"^28-[0-9a-f]{12}$")


def _now() -> int:
    return int(time.time())


class SensorStore:
    def __init__(self, db_path: Path, clock: Callable[[], float] = time.time) -> None:
        self._db = db_path
        self._clock = clock
        self.relay_pins: Callable[[], dict[int, str]] = lambda: {}
        """GPIO pins used by relays, set by the app (relays and sensors must not share)."""

    # --- reading ------------------------------------------------------------------------

    def all(self) -> list[SensorConfig]:
        with transaction(self._db) as conn:
            rows = conn.execute("SELECT * FROM sensors ORDER BY created_at, name").fetchall()
        return [SensorConfig(r["id"], r["name"], r["kind"], json.loads(r["config"])) for r in rows]

    def get(self, sensor_id: str) -> SensorConfig:
        for sensor in self.all():
            if sensor.id == sensor_id:
                return sensor
        raise NotFound(f"sensor {sensor_id} not found")

    def gpio_pins(self, ignore: str | None = None) -> dict[int, str]:
        """GPIO pin -> sensor name, for the sensors that use a pin."""
        pins: dict[int, str] = {}
        for sensor in self.all():
            if sensor.id != ignore and "pin" in sensor.config:
                pins[int(sensor.config["pin"])] = sensor.name
            if sensor.id != ignore and sensor.kind == "ds18b20":
                pins.setdefault(int(sensor.config.get("bus_pin", 4)), "the 1-Wire bus")
        return pins

    def onewire_pin(self) -> int | None:
        for sensor in self.all():
            if sensor.kind == "ds18b20":
                return int(sensor.config.get("bus_pin", 4))
        return None

    # --- first start ------------------------------------------------------------------------

    def effective(self, settings: Settings) -> list[SensorConfig]:
        """The sensors to use. On the very first start of 0.9.0, carry over the old setup."""
        with transaction(self._db) as conn:
            done = conn.execute("SELECT imported_at FROM sensor_setup WHERE id = 1").fetchone()
        if done is None:
            for name, kind, config in self._carry_over(settings):
                self._insert(name, kind, config)
            with transaction(self._db) as conn:
                conn.execute("INSERT INTO sensor_setup (id, imported_at) VALUES (1, ?)", (_now(),))
        return self.all()

    def _carry_over(self, settings: Settings) -> list[tuple[str, str, dict[str, Any]]]:
        demo = settings.hardware == "mock"
        set_in_env = settings.model_fields_set
        with transaction(self._db) as conn:
            had_climate = conn.execute(
                "SELECT 1 FROM sensor_samples WHERE ok = 1 LIMIT 1"
            ).fetchone()
            had_water = conn.execute(
                "SELECT 1 FROM water_level_samples WHERE ok = 1 LIMIT 1"
            ).fetchone()
            had_gps = conn.execute("SELECT 1 FROM gps_fixes LIMIT 1").fetchone()
        found: list[tuple[str, str, dict[str, Any]]] = []
        if demo or "dht22_sensors" in set_in_env or had_climate:
            found += [(s.name, "dht22", {"pin": s.gpio_pin}) for s in settings.dht22_sensors]
        gps_wanted = settings.gps_enabled and (demo or "gps_enabled" in set_in_env or had_gps)
        if gps_wanted:
            found.append(("gps", "gps", {"device": settings.gps_device, "baud": settings.gps_baud}))
        if demo or had_water:
            found.append(("tank", "water_tank", {}))
        return found

    # --- changing ---------------------------------------------------------------------------

    def _insert(self, name: str, kind: str, config: dict[str, Any]) -> str:
        sensor_id = uuid.uuid4().hex[:12]
        with transaction(self._db) as conn:
            conn.execute(
                "INSERT INTO sensors (id, name, kind, config, created_at) VALUES (?, ?, ?, ?, ?)",
                (sensor_id, name, kind, json.dumps(config), int(self._clock())),
            )
        return sensor_id

    def validate(
        self, name: str, kind: str, config: dict[str, Any], ignore: str | None = None
    ) -> dict[str, Any]:
        """Check a sensor's settings; returns the cleaned config. Raises InvalidInput/Conflict."""
        if kind not in KINDS:
            raise InvalidInput(f"unknown sensor type {kind!r}")
        if not NAME.match(name):
            raise InvalidInput(
                "the name is lowercase letters, digits and _ (used in rules), e.g. fridge"
            )
        others = [s for s in self.all() if s.id != ignore]
        if any(s.name == name for s in others):
            raise Conflict(f"there is already a sensor called {name!r}")
        if kind in SINGLE_KINDS and any(s.kind == kind for s in others):
            raise Conflict("a van has only one of these; edit the existing one")
        clean: dict[str, Any] = {}
        if kind in GPIO_KINDS:
            clean["pin"] = self._check_pin(config.get("pin"), ignore)
        if kind == "door":
            clean["closed_when"] = "high" if config.get("closed_when") == "high" else "low"
        if kind == "ds18b20":
            rom = str(config.get("rom", "")).strip().lower()
            if not ROM_ID.match(rom):
                raise InvalidInput(
                    "pick the probe from the list (its id looks like 28-0123456789ab)"
                )
            if any(s.kind == "ds18b20" and s.config.get("rom") == rom for s in others):
                raise Conflict("this probe is already added")
            bus = int(config.get("bus_pin", self.onewire_pin() or 4))
            clean["rom"], clean["bus_pin"] = rom, bus
        if kind in I2C_ADDRESSES:
            address = config.get("address", I2C_ADDRESSES[kind][0])
            address = int(address, 16) if isinstance(address, str) else int(address)
            if address not in I2C_ADDRESSES[kind]:
                choices = " or ".join(hex(a) for a in I2C_ADDRESSES[kind])
                raise InvalidInput(f"this sensor's I2C address is {choices}")
            if any(s.config.get("address") == address for s in others):
                raise Conflict(f"another sensor already uses I2C address {hex(address)}")
            clean["address"] = address
        if kind == "gps":
            device = str(config.get("device") or "/dev/serial0")
            if not device.startswith("/dev/"):
                raise InvalidInput("the GPS port looks like /dev/serial0")
            baud = int(config.get("baud") or 9600)
            if baud not in (4800, 9600, 19200, 38400, 57600, 115200):
                raise InvalidInput("unusual GPS speed; most modules use 9600")
            clean["device"], clean["baud"] = device, baud
        return clean

    def _check_pin(self, value: Any, ignore: str | None) -> int:
        try:
            pin = int(value)
        except (TypeError, ValueError):
            raise InvalidInput("choose the GPIO pin the sensor's data wire is on") from None
        if pin in RESERVED_PINS:
            raise Conflict(f"GPIO {pin} is used by {RESERVED_PINS[pin]}")
        if pin not in USABLE_PINS:
            raise InvalidInput("GPIO pins on the Pi are 2 to 27")
        used = {
            **{p: f"relay '{n}'" for p, n in self.relay_pins().items()},
            **self.gpio_pins(ignore),
        }
        if pin in used:
            raise Conflict(f"GPIO {pin} is already used by {used[pin]}")
        return pin

    def add(self, name: str, kind: str, config: dict[str, Any]) -> SensorConfig:
        clean = self.validate(name, kind, config)
        return self.get(self._insert(name, kind, clean))

    def update(
        self, sensor_id: str, name: str | None, config: dict[str, Any] | None
    ) -> SensorConfig:
        sensor = self.get(sensor_id)
        name = name if name is not None else sensor.name
        clean = self.validate(
            name, sensor.kind, {**sensor.config, **(config or {})}, ignore=sensor_id
        )
        with transaction(self._db) as conn:
            conn.execute(
                "UPDATE sensors SET name = ?, config = ? WHERE id = ?",
                (name, json.dumps(clean), sensor_id),
            )
        return self.get(sensor_id)

    def remove(self, sensor_id: str) -> SensorConfig:
        sensor = self.get(sensor_id)
        with transaction(self._db) as conn:
            conn.execute("DELETE FROM sensors WHERE id = ?", (sensor_id,))
        return sensor

    def pin_map(self) -> list[dict[str, Any]]:
        """Every GPIO pin and what uses it, for the wiring helper."""
        used = {**{p: f"relay {n}" for p, n in self.relay_pins().items()}, **self.gpio_pins()}
        result = []
        for pin in range(0, 28):
            if pin in RESERVED_PINS:
                result.append({"gpio": pin, "free": False, "used_by": RESERVED_PINS[pin]})
            else:
                result.append({"gpio": pin, "free": pin not in used, "used_by": used.get(pin)})
        return result


def as_dict(sensor: SensorConfig) -> dict[str, Any]:
    return asdict(sensor)
