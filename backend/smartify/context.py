"""Wires settings, hardware, services and workers together."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from smartify.config import Settings
from smartify.hardware import Hardware
from smartify.logbuffer import LogBuffer
from smartify.services.climate import ClimateService
from smartify.services.gps import GpsService
from smartify.services.maintenance import prune_history
from smartify.services.relays import RelayService
from smartify.services.rules import RuleService
from smartify.services.water import WaterService
from smartify.services.weather import WeatherService
from smartify.services.wifi import MockWifi, NmcliWifi, WifiBackend
from smartify.workers import Worker

log = logging.getLogger(__name__)


@dataclass
class AppContext:
    settings: Settings
    hardware: Hardware
    logs: LogBuffer
    climate: ClimateService
    rules: RuleService
    relays: RelayService
    water: WaterService
    gps: GpsService
    weather: WeatherService
    wifi: WifiBackend
    started_at: float = field(default_factory=time.time)
    workers: list[Worker] = field(default_factory=list)

    @classmethod
    def build(cls, settings: Settings, hardware: Hardware, logs: LogBuffer) -> AppContext:
        db = settings.db_path
        climate = ClimateService(settings, hardware.climate_sensors, db)
        rules = RuleService(db, climate.metric)
        gps = GpsService(hardware.gps, db)
        return cls(
            settings=settings,
            hardware=hardware,
            logs=logs,
            climate=climate,
            rules=rules,
            relays=RelayService(settings, hardware.relays, rules, db),
            water=WaterService(hardware.analog, db),
            gps=gps,
            weather=WeatherService(gps, db, settings.weather_interval_seconds),
            wifi=MockWifi() if settings.hardware == "mock" else NmcliWifi(settings.wifi_interface),
        )

    def start(self) -> None:
        self.relays.startup()
        s = self.settings
        self.workers = [
            Worker("climate", s.sensor_interval_seconds, self.climate.sample),
            Worker("water", s.water_interval_seconds, self.water.sample),
            Worker("rules", s.rule_interval_seconds, self.relays.reconcile_all),
            Worker("history", 60, self._flush_history),
            Worker("maintenance", 6 * 3600, self._maintenance),
        ]
        if self.gps.enabled:
            self.workers.append(Worker("gps", 1, self.gps.poll))
        if s.weather_enabled:
            self.workers.append(Worker("weather", 60, self.weather.refresh_if_due))
        for worker in self.workers:
            worker.start()
        log.info("Started %d workers", len(self.workers))

    def stop(self) -> None:
        for worker in self.workers:
            worker.stop()
        if self.hardware.gps is not None:
            self.hardware.gps.close()

    def _flush_history(self) -> None:
        self.climate.flush_minute()
        self.water.flush_minute()

    def _maintenance(self) -> None:
        prune_history(self.settings.db_path, self.settings.retention_days)
