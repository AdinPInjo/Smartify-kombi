"""Hardware access. Use :func:`build_hardware` to get drivers for the configured mode."""

from __future__ import annotations

import logging
from typing import Any

from smartify.config import Settings
from smartify.hardware.base import (
    AnalogReader,
    ClimateReading,
    ClimateSensor,
    DiscoveredVictron,
    GpsFix,
    GpsReceiver,
    Hardware,
    HardwareError,
    RelayDriver,
    SensorConfig,
    VictronListener,
    VictronReading,
)

log = logging.getLogger(__name__)

__all__ = [
    "AnalogReader",
    "ClimateReading",
    "ClimateSensor",
    "DiscoveredVictron",
    "GpsFix",
    "GpsReceiver",
    "Hardware",
    "HardwareError",
    "RelayDriver",
    "VictronListener",
    "VictronReading",
    "build_hardware",
    "build_relay_driver",
]


def build_relay_driver(settings: Settings) -> RelayDriver:
    """Only the relay driver (used by the failsafe command)."""
    if settings.hardware == "mock":
        from smartify.hardware.mock import MockRelayDriver

        return MockRelayDriver()
    from smartify.hardware.pi.relays import PinctrlRelayDriver

    return PinctrlRelayDriver()


CLIMATE_KINDS = {"dht22", "dht11", "ds18b20", "bme280", "sht31", "aht20"}


class FailedSensor:
    """Stands in for a sensor whose driver could not start, so the error shows up."""

    def __init__(self, name: str, error: str) -> None:
        self.name = name
        self._error = error

    def read(self) -> ClimateReading:
        return ClimateReading(self.name, None, None, error=self._error)


def climate_sensors(factory: Any, configs: list[SensorConfig]) -> list[ClimateSensor]:
    sensors: list[ClimateSensor] = []
    for config in configs:
        if config.kind not in CLIMATE_KINDS:
            continue
        try:
            sensors.append(factory.climate(config))
        except HardwareError as exc:
            # A broken sensor must not stop the relays from working.
            log.error("Sensor %r unavailable: %s", config.name, exc)
            sensors.append(FailedSensor(config.name, str(exc)))
    return sensors


def build_hardware(settings: Settings, sensors: list[SensorConfig] | None = None) -> Hardware:
    """``sensors``: the dashboard's sensor list. None: the old .env setup (tests, tools)."""
    if sensors is None:
        sensors = [
            SensorConfig(s.name, s.name, "dht22", {"pin": s.gpio_pin})
            for s in settings.dht22_sensors
        ]
        if settings.gps_enabled:
            sensors.append(
                SensorConfig(
                    "gps", "gps", "gps", {"device": settings.gps_device, "baud": settings.gps_baud}
                )
            )
    gps_config = next((s.config for s in sensors if s.kind == "gps"), None)
    if settings.hardware == "mock":
        return _build_mock(settings, sensors, gps_config)
    return _build_pi(settings, sensors, gps_config)


def _build_mock(
    settings: Settings, sensors: list[SensorConfig], gps_config: dict | None
) -> Hardware:
    from smartify.hardware import mock

    relays = mock.MockRelayDriver()
    pins = {seed.name: seed.gpio_pin for seed in settings.default_relays}
    cabin = mock.MockCabin(relays, heater_pin=pins.get("heater"), fan_pin=pins.get("fan"))
    factory = mock.MockSensorFactory(cabin)
    climate = climate_sensors(factory, sensors)
    gps = mock.MockGpsReceiver() if gps_config is not None else None
    log.info("Using simulated hardware (%d climate sensors)", len(climate))
    return Hardware(
        relays=relays,
        climate_sensors=climate,
        analog=mock.MockAnalogReader(),
        gps=gps,
        victron=mock.MockVictronListener(),
        heaters=mock.MockHeaters(),
        sensors=factory,
    )


def _build_pi(settings: Settings, sensors: list[SensorConfig], gps_config: dict | None) -> Hardware:
    from smartify.hardware.pi.ads1115 import Ads1115Reader
    from smartify.hardware.pi.gps import SerialGpsReceiver
    from smartify.hardware.pi.relays import PinctrlRelayDriver
    from smartify.hardware.pi.sensors import PiSensorFactory

    analog = Ads1115Reader(settings.ads1115_bus, settings.ads1115_address)
    factory = PiSensorFactory(analog)
    climate = climate_sensors(factory, sensors)
    gps = None
    if gps_config is not None:
        gps = SerialGpsReceiver(
            gps_config.get("device", settings.gps_device),
            int(gps_config.get("baud", settings.gps_baud)),
            ublox_tuning=settings.gps_ublox_tuning,
        )
    # Always listen, so Victron devices can be found and added from the dashboard.
    victron = None
    try:
        from smartify.hardware.pi.victron import BleVictronListener

        victron = BleVictronListener(settings.victron_devices)
    except HardwareError:
        log.exception("Bluetooth support for Victron devices is missing")
    heaters = None
    try:
        from smartify.hardware.pi.heater import BleHeaters

        heaters = BleHeaters()
    except HardwareError:
        log.exception("Bluetooth support for diesel heaters is missing")
    log.info("Using Raspberry Pi hardware (%d climate sensors)", len(climate))
    return Hardware(
        relays=PinctrlRelayDriver(),
        climate_sensors=climate,
        analog=analog,
        gps=gps,
        victron=victron,
        heaters=heaters,
        sensors=factory,
    )
