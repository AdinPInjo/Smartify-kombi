"""Application settings.

Every setting can be overridden with an environment variable prefixed with
``SMARTIFY_`` (for example ``SMARTIFY_HARDWARE=mock``) or through a ``.env``
file in the working directory. See ``.env.example`` in the repository root.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class RelaySeed(BaseModel):
    """A relay created on first start when the relay table is empty."""

    name: str
    gpio_pin: int = Field(ge=0, le=27)


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
    secret_key: str = "change-this-secret"

    # --- Sensors -----------------------------------------------------------
    dht22_pins: Annotated[list[int], NoDecode] = Field(default_factory=lambda: [4, 17])
    """BCM pin numbers of DHT22 sensors, comma separated in the env var."""

    sensor_interval_seconds: float = Field(default=5.0, gt=0)

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

    # --- GPS ---------------------------------------------------------------
    gps_enabled: bool = True
    gps_device: str = "/dev/serial0"
    gps_baud: int = 9600

    @field_validator("dht22_pins", mode="before")
    @classmethod
    def _parse_pins(cls, value: object) -> object:
        parts = _split_csv(value)
        if isinstance(parts, list):
            return [int(p) for p in parts]
        return parts

    @field_validator("default_relays", mode="before")
    @classmethod
    def _parse_relays(cls, value: object) -> object:
        parts = _split_csv(value)
        if isinstance(parts, list) and parts and isinstance(parts[0], str):
            seeds = []
            for part in parts:
                name, _, pin = part.partition(":")
                if not name or not pin:
                    raise ValueError(f"Relay entry {part!r} must look like name:pin")
                seeds.append({"name": name.strip(), "gpio_pin": int(pin)})
            return seeds
        return parts

    @property
    def db_path(self) -> Path:
        return self.data_dir / self.db_filename

    @property
    def uses_default_credentials(self) -> bool:
        return self.password == "changeme" or self.secret_key == "change-this-secret"


@lru_cache
def get_settings() -> Settings:
    return Settings()
