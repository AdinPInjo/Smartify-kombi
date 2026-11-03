"""Hardware interfaces.

Services only talk to these interfaces. ``hardware/pi`` implements them for a
Raspberry Pi and ``hardware/mock`` simulates them, so the whole application can
run and be tested on a laptop.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ClimateReading:
    """One reading from a temperature/humidity sensor."""

    sensor: str
    temperature_c: float | None
    humidity: float | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.temperature_c is not None


@dataclass(frozen=True)
class GpsFix:
    lat: float
    lon: float
    speed_kmh: float | None = None
    course: float | None = None
    altitude_m: float | None = None
    satellites: int | None = None
    hdop: float | None = None


class RelayDriver(Protocol):
    def set_state(self, gpio_pin: int, on: bool, active_low: bool) -> None:
        """Drive the pin. Raises ``HardwareError`` on failure."""


class ClimateSensor(Protocol):
    name: str

    def read(self) -> ClimateReading:
        """Read once. Never raises; failures are reported in ``ClimateReading.error``."""


class AnalogReader(Protocol):
    def read_voltages(self, channels: tuple[int, ...]) -> tuple[float, ...]:
        """Read single-ended voltages for the given channels. Raises ``HardwareError``."""


class GpsReceiver(Protocol):
    def read_fix(self, timeout_seconds: float) -> GpsFix | None:
        """Return the next valid fix, or ``None`` if there is no fix yet.

        Raises ``HardwareError`` if the receiver cannot be reached.
        """

    def close(self) -> None: ...


@dataclass(frozen=True)
class VictronReading:
    """Decoded Instant Readout data from one Victron device."""

    device: str
    """Name from the configuration, e.g. 'shunt'."""
    kind: str
    """battery_monitor, solar_charger, dcdc_converter, inverter_charger, ..."""
    model: str | None
    values: dict[str, float | int | str | None]
    rssi: int | None = None


class VictronListener(Protocol):
    def start(self, on_reading: Callable[[VictronReading], None]) -> None:
        """Start listening in the background; call ``on_reading`` for every advertisement."""

    def stop(self) -> None: ...


class HardwareError(RuntimeError):
    """A device could not be reached or returned invalid data."""


@dataclass
class Hardware:
    """Everything the services need from the outside world."""

    relays: RelayDriver
    climate_sensors: list[ClimateSensor]
    analog: AnalogReader
    gps: GpsReceiver | None
    victron: VictronListener | None = None
