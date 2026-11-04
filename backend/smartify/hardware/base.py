"""Hardware interfaces.

Services only talk to these interfaces. ``hardware/pi`` implements them for a
Raspberry Pi and ``hardware/mock`` simulates them, so the whole application can
run and be tested on a laptop.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol


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


@dataclass(frozen=True)
class DiscoveredVictron:
    """A Victron device heard over Bluetooth, configured or not."""

    mac: str
    name: str | None
    """Bluetooth name, e.g. "SmartShunt HQ2142ABCDE"."""
    kind: str | None
    rssi: int | None
    seen_at: int


class VictronListener(Protocol):
    def start(self, on_reading: Callable[[VictronReading], None]) -> None:
        """Start listening in the background; call ``on_reading`` for every advertisement."""

    def stop(self) -> None: ...

    def set_devices(self, devices: list[Any]) -> None:
        """Replace the configured devices (``VictronDevice``) while running."""

    def discovered(self) -> list[DiscoveredVictron]:
        """Victron devices heard in the last minutes."""
        ...

    def check_key(self, mac: str, key: str) -> bool | None:
        """Whether ``key`` decrypts the device's data; None if not heard yet."""
        ...

    @property
    def error(self) -> str | None: ...


@dataclass(frozen=True)
class DiscoveredHeater:
    """A diesel heater controller heard over Bluetooth."""

    mac: str
    name: str | None
    rssi: int | None
    seen_at: int


@dataclass(frozen=True)
class HeaterConfig:
    """A heater added in the dashboard."""

    id: str
    name: str
    mac: str
    pin: int


@dataclass
class HeaterStatus:
    """What the heater reports, the same for every brand and protocol."""

    running: bool
    phase: str
    """standby, self_test, ignition, running, cooldown, ventilation or fault."""
    mode: str | None
    """"temperature" (keeps the cabin at a temperature) or "level" (fixed power)."""
    target_temperature: float | None
    level: int | None
    cabin_temperature: float | None
    heater_temperature: float | None
    voltage: float | None
    error_code: int | None
    error: str | None
    co_ppm: float | None
    protocol: str | None
    updated_at: int


@dataclass
class HeaterLink:
    """Connection state of one configured heater."""

    connected: bool
    status: HeaterStatus | None
    error: str | None
    """Why it is not connected, in plain words."""
    last_seen: int | None


class HeaterBackend(Protocol):
    """Talks to diesel heaters (Bluetooth on the Pi, simulated in mock mode)."""

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def set_heaters(self, heaters: list[HeaterConfig]) -> None:
        """Connect to these heaters (and drop the others)."""

    def link(self, heater_id: str) -> HeaterLink: ...

    def discovered(self) -> list[DiscoveredHeater]:
        """Heater controllers nearby. The first call starts a short scan."""
        ...

    def command(self, heater_id: str, command: int, argument: int = 0) -> None:
        """Send one command (heater_protocol.CMD_*). Raises HardwareError."""


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
    heaters: HeaterBackend | None = None
