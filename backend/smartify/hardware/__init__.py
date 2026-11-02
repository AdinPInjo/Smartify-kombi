"""Hardware access. Use :func:`build_hardware` to get drivers for the configured mode."""

from __future__ import annotations

import logging

from smartify.config import Settings
from smartify.hardware.base import (
    AnalogReader,
    ClimateReading,
    ClimateSensor,
    GpsFix,
    GpsReceiver,
    Hardware,
    HardwareError,
    RelayDriver,
)

log = logging.getLogger(__name__)

__all__ = [
    "AnalogReader",
    "ClimateReading",
    "ClimateSensor",
    "GpsFix",
    "GpsReceiver",
    "Hardware",
    "HardwareError",
    "RelayDriver",
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


def build_hardware(settings: Settings) -> Hardware:
    if settings.hardware == "mock":
        return _build_mock(settings)
    return _build_pi(settings)


def _build_mock(settings: Settings) -> Hardware:
    from smartify.hardware import mock

    relays = mock.MockRelayDriver()
    pins = {seed.name: seed.gpio_pin for seed in settings.default_relays}
    cabin = mock.MockCabin(relays, heater_pin=pins.get("heater"), fan_pin=pins.get("fan"))
    sensors = [
        # Every sensor after the first reads a bit colder, like an outside sensor would.
        mock.MockClimateSensor(sensor.name, cabin, offset=-6.0 * min(i, 1))
        for i, sensor in enumerate(settings.dht22_sensors)
    ]
    gps = mock.MockGpsReceiver() if settings.gps_enabled else None
    log.info("Using simulated hardware (%d climate sensors)", len(sensors))
    return Hardware(relays=relays, climate_sensors=sensors, analog=mock.MockAnalogReader(), gps=gps)


def _build_pi(settings: Settings) -> Hardware:
    from smartify.hardware.pi.ads1115 import Ads1115Reader
    from smartify.hardware.pi.dht22 import Dht22Sensor
    from smartify.hardware.pi.gps import SerialGpsReceiver
    from smartify.hardware.pi.relays import PinctrlRelayDriver

    sensors: list[ClimateSensor] = []
    for sensor in settings.dht22_sensors:
        try:
            sensors.append(Dht22Sensor(sensor.name, sensor.gpio_pin))
        except HardwareError:
            # A missing sensor must not stop the relays from working.
            log.exception("DHT22 %r on GPIO %d unavailable", sensor.name, sensor.gpio_pin)

    gps = None
    if settings.gps_enabled:
        gps = SerialGpsReceiver(settings.gps_device, settings.gps_baud)
    log.info("Using Raspberry Pi hardware (%d climate sensors)", len(sensors))
    return Hardware(
        relays=PinctrlRelayDriver(),
        climate_sensors=sensors,
        analog=Ads1115Reader(settings.ads1115_bus, settings.ads1115_address),
        gps=gps,
    )
