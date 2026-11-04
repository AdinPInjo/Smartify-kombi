"""Application settings.

Every setting can be overridden with an environment variable prefixed with
``SMARTIFY_`` (for example ``SMARTIFY_HARDWARE=mock``) or through a ``.env``
file in the working directory. See ``.env.example`` in the repository root.
"""

from __future__ import annotations

import os
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEFAULT_PASSWORD = "changeme"


class RelaySeed(BaseModel):
    """A relay created on first start when the relay table is empty."""

    name: str = Field(pattern=r"^[a-z0-9_-]{1,32}$")
    gpio_pin: int = Field(ge=0, le=27)


class SensorPin(BaseModel):
    """A DHT22 sensor: the name used in the dashboard and in rules, and its GPIO."""

    name: str = Field(pattern=r"^[a-z0-9_-]{1,32}$")
    gpio_pin: int = Field(ge=0, le=27)


class VictronDevice(BaseModel):
    """A Victron device read over Bluetooth (Instant Readout)."""

    name: str = Field(pattern=r"^[a-z0-9_-]{1,32}$")
    mac: str = Field(pattern=r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")
    key: str = Field(pattern=r"^[0-9A-Fa-f]{32}$", repr=False)
    """Encryption key from VictronConnect: Product info > Instant readout details."""


def _parse_victron(value: object) -> object:
    parts = _split_csv(value)
    if isinstance(parts, list) and all(isinstance(p, str) for p in parts):
        devices = []
        for part in parts:
            fields = [f.strip() for f in part.split("|")]
            if len(fields) != 3:
                raise ValueError(f"Victron entry {part!r} must look like name|MAC|key")
            devices.append({"name": fields[0], "mac": fields[1], "key": fields[2]})
        return devices
    return parts


def _parse_name_pin_pairs(value: object) -> object:
    parts = _split_csv(value)
    if isinstance(parts, list) and all(isinstance(p, str) for p in parts):
        pairs = []
        for part in parts:
            name, _, pin = part.partition(":")
            if not name.strip() or not pin.strip():
                raise ValueError(f"Entry {part!r} must look like name:pin")
            pairs.append({"name": name.strip(), "gpio_pin": int(pin)})
        return pairs
    return parts


def _split_csv(value: object) -> object:
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SMARTIFY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Runtime -----------------------------------------------------------
    hardware: Literal["pi", "mock"] = "mock"
    """``pi`` talks to real GPIO/I2C/serial devices, ``mock`` simulates them."""

    host: str = "0.0.0.0"
    port: int = 8000
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    data_dir: Path = Path("data")
    db_filename: str = "smartify.db"

    frontend_dir: Path | None = None
    """Directory with the built dashboard (``frontend/dist``). Optional."""

    # --- Authentication ----------------------------------------------------
    username: str = "admin"
    password: str = "changeme"
    """Old .env login. The default only works with simulated hardware; a real van
    creates its login in the dashboard (first-run setup, with the setup code)."""
    secret_key: str = ""
    """Signs login cookies. Leave empty to generate one and keep it in the data directory."""

    # --- Sensors -----------------------------------------------------------
    dht22_sensors: Annotated[list[SensorPin], NoDecode] = Field(
        default_factory=lambda: [
            SensorPin(name="inside", gpio_pin=4),
            SensorPin(name="outside", gpio_pin=17),
        ]
    )
    """DHT22 sensors as ``name:BCM pin`` pairs, comma separated."""

    sensor_interval_seconds: float = Field(default=5.0, ge=2.5)
    """How often each DHT22 is read. The DHT22 itself needs at least 2 s."""

    sensor_window_seconds: int = Field(default=60, ge=10)
    """Readings are averaged over this window before rules use them."""

    sensor_min_samples: int = Field(default=3, ge=1)
    """Good readings needed in the window before a sensor counts as ready."""

    sensor_stale_seconds: int = Field(default=600, ge=30)
    """Without a good reading for this long, rules using the sensor switch their relay off."""

    water_interval_seconds: float = Field(default=10.0, ge=1)

    ads1115_bus: int = 1
    ads1115_address: int = 0x48

    # --- Relays ------------------------------------------------------------
    default_relays: Annotated[list[RelaySeed], NoDecode] = Field(
        default_factory=lambda: [
            RelaySeed(name="heater", gpio_pin=25),
            RelaySeed(name="fan", gpio_pin=26),
        ]
    )
    """``name:pin`` pairs, comma separated. Only used when no relays exist yet."""

    rule_interval_seconds: float = Field(default=5.0, ge=1)
    """How often automatic relays are re-evaluated against their rules."""

    # --- GPS ---------------------------------------------------------------
    gps_enabled: bool = True
    gps_device: str = "/dev/serial0"
    gps_baud: int = 9600
    gps_ublox_tuning: bool = True
    """Send u-blox static hold + SBAS settings on connect (other receivers ignore them)."""

    # --- Weather (Open-Meteo, free, no API key) ------------------------------
    weather_enabled: bool = True
    weather_interval_seconds: int = Field(default=1800, ge=300)

    # --- Victron (Bluetooth Instant Readout) ---------------------------------
    victron_devices: Annotated[list[VictronDevice], NoDecode] = Field(default_factory=list)
    """``name|MAC|key`` entries, comma separated. In mock mode, an empty list
    simulates a SmartShunt, SmartSolar MPPT, Orion and MultiPlus."""

    victron_stale_seconds: int = Field(default=120, ge=10)

    # --- Remote dashboard (cloud/ on any PHP + MySQL hosting) ------------------
    cloud_url: str = ""
    """Base URL of your cloud install, e.g. https://kombi.example.com. Empty = off."""
    cloud_token: str = Field(default="", repr=False)
    """Device token shown by the cloud installer."""
    cloud_interval_seconds: float = Field(default=10, ge=3)
    """How often the Pi asks the cloud for commands (remote switch delay)."""
    cloud_state_seconds: float = Field(default=60, ge=10)
    """How often live values and history are uploaded (mobile data use)."""

    # --- Updates (Settings → Updates) -----------------------------------------
    update_repo: str = "AdinPInjo/Smartify-kombi"
    """GitHub project (owner/name) whose releases the van installs."""
    update_check_hours: float = Field(default=6, ge=1)
    """How often to look for a new version (unless updates are off)."""
    updater_unit: Path = Path("/etc/systemd/system/smartify-update.path")
    """Installed by deploy/install.sh; without it the dashboard can't install updates."""

    # --- WiFi (NetworkManager / nmcli) ---------------------------------------
    wifi_interface: str = "wlan0"

    # --- Storage -----------------------------------------------------------
    retention_days: int = Field(default=90, ge=1)
    """Sensor, water, GPS and weather history older than this is deleted daily."""

    @field_validator("victron_devices", mode="before")
    @classmethod
    def _parse_victron_devices(cls, value: object) -> object:
        return _parse_victron(value)

    @field_validator("dht22_sensors", "default_relays", mode="before")
    @classmethod
    def _parse_pairs(cls, value: object) -> object:
        return _parse_name_pin_pairs(value)

    @property
    def db_path(self) -> Path:
        return self.data_dir / self.db_filename

    @property
    def uses_default_credentials(self) -> bool:
        return self.password == DEFAULT_PASSWORD

    def resolved_secret_key(self) -> str:
        """The configured secret, or a random one generated once and stored in data_dir."""
        if self.secret_key:
            return self.secret_key
        path = self.data_dir / "secret_key"
        try:
            return path.read_text().strip()
        except FileNotFoundError:
            pass
        self.data_dir.mkdir(parents=True, exist_ok=True)
        key = secrets.token_urlsafe(48)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(key)
        return key


@lru_cache
def get_settings() -> Settings:
    return Settings()
