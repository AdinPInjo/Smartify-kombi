"""Wires settings, hardware, services and workers together."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from smartify import systemd
from smartify.config import Settings
from smartify.hardware import Hardware
from smartify.logbuffer import LogBuffer
from smartify.services.alerts import AlertService
from smartify.services.climate import ClimateService
from smartify.services.cloud_sync import CloudSync, apply_command
from smartify.services.conditions import (
    CLIMATE_METRICS,
    GPS_SENSOR,
    WATER_SENSOR,
    MetricValue,
    SensorIssue,
)
from smartify.services.energy import EnergyService
from smartify.services.gps import GpsService
from smartify.services.maintenance import backup, check_integrity, prune_history
from smartify.services.notify import NotificationService
from smartify.services.relays import RelayService
from smartify.services.rules import RuleService
from smartify.services.snapshot import build_state
from smartify.services.trips import TripService
from smartify.services.victron_setup import VictronDevices
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
    energy: EnergyService
    rules: RuleService
    relays: RelayService
    water: WaterService
    gps: GpsService
    weather: WeatherService
    wifi: WifiBackend
    notifications: NotificationService
    trips: TripService
    victron: VictronDevices
    alerts: AlertService = field(init=False)
    cloud: CloudSync | None = None
    started_at: float = field(default_factory=time.time)
    workers: list[Worker] = field(default_factory=list)

    @classmethod
    def build(cls, settings: Settings, hardware: Hardware, logs: LogBuffer) -> AppContext:
        db = settings.db_path
        climate = ClimateService(settings, hardware.climate_sensors, db)
        energy = EnergyService(db, settings.victron_stale_seconds)
        victron = VictronDevices(db, settings.victron_devices, hardware.victron)

        gps = GpsService(hardware.gps, db)
        water = WaterService(
            hardware.analog, db, stale_seconds=max(60, settings.water_interval_seconds * 6)
        )

        def metric(sensor: str, name: str) -> MetricValue:
            if name in CLIMATE_METRICS:
                return climate.metric(sensor, name)
            if name == "water_level":
                if sensor != WATER_SENSOR:
                    return MetricValue(None, SensorIssue.MISSING)
                return water.metric(sensor, name)
            if name == "speed":
                if sensor != GPS_SENSOR or not gps.enabled:
                    return MetricValue(None, SensorIssue.MISSING)
                return gps.metric(sensor, name)
            return energy.metric(sensor, name)

        def sensors_for(name: str) -> list[str]:
            if name in CLIMATE_METRICS:
                return climate.sensor_names
            if name == "water_level":
                return [WATER_SENSOR]
            if name == "speed":
                return [GPS_SENSOR] if gps.enabled else []
            # Configured devices count even before their first advertisement.
            configured = victron.names()
            return sorted(set(configured) | set(energy.devices_for(name)))

        rules = RuleService(db, metric, sensors_for)
        notifications = NotificationService(db)
        ctx = cls(
            settings=settings,
            hardware=hardware,
            logs=logs,
            climate=climate,
            energy=energy,
            rules=rules,
            relays=RelayService(settings, hardware.relays, rules, db),
            water=water,
            gps=gps,
            weather=WeatherService(gps, db, settings.weather_interval_seconds),
            wifi=MockWifi() if settings.hardware == "mock" else NmcliWifi(settings.wifi_interface),
            notifications=notifications,
            trips=TripService(gps, db),
            victron=victron,
        )
        ctx.alerts = AlertService(ctx, notifications, db)
        return ctx

    def start(self) -> None:
        check_integrity(self.settings.db_path)
        self.relays.startup()
        if self.hardware.victron is not None:
            self.victron.apply()  # devices added from the dashboard
            self.hardware.victron.start(self.energy.on_reading)
        s = self.settings
        self.workers = [
            Worker("climate", s.sensor_interval_seconds, self.climate.sample),
            Worker("water", s.water_interval_seconds, self.water.sample),
            Worker("rules", s.rule_interval_seconds, self.relays.reconcile_all),
            Worker("history", 60, self._flush_history),
            Worker("maintenance", 6 * 3600, self._maintenance),
            Worker("alerts", 10, self.alerts.check),
            Worker("notify", 10, self.notifications.deliver_due),
        ]
        if self.gps.enabled:
            self.workers.append(Worker("gps", 1, self.gps.poll))
            self.workers.append(Worker("trips", 30, self.trips.tick))
        if s.weather_enabled:
            self.workers.append(Worker("weather", 60, self.weather.refresh_if_due))
        if s.cloud_url and s.cloud_token:
            self.cloud = CloudSync(
                url=s.cloud_url,
                token=s.cloud_token,
                db_path=s.db_path,
                state_seconds=s.cloud_state_seconds,
                build_state=lambda: build_state(self),
                apply_command=lambda command: apply_command(self, command),
            )
            self.workers.append(Worker("cloud", s.cloud_interval_seconds, self.cloud.tick))
            log.info("Remote dashboard sync to %s", s.cloud_url)
        self.workers.append(Worker("heartbeat", 10, self._heartbeat))
        for worker in self.workers:
            worker.start()
        log.info("Started %d workers", len(self.workers))
        systemd.notify("READY=1")

    def stop(self) -> None:
        for worker in self.workers:
            worker.stop()
        if self.hardware.victron is not None:
            self.hardware.victron.stop()
        # Nothing controls the relays once we exit, so leave them off.
        self.relays.all_off("shutdown", "service stopped")
        if self.hardware.gps is not None:
            self.hardware.gps.close()

    def _flush_history(self) -> None:
        self.climate.flush_minute()
        self.water.flush_minute()
        self.energy.flush_minute()

    def _maintenance(self) -> None:
        prune_history(self.settings.db_path, self.settings.retention_days)
        self.notifications.prune()
        backup(self.settings.db_path)

    def _heartbeat(self) -> None:
        """Tell systemd we are alive, but only while the rules worker keeps running.

        If rule evaluation hangs, the heartbeat stops, systemd restarts the
        service and its ExecStopPost switches every relay off.
        """
        rules = next(w for w in self.workers if w.name == "rules").status()
        limit = max(30.0, self.settings.rule_interval_seconds * 6)
        if rules.last_run_at is not None and time.time() - rules.last_run_at < limit:
            systemd.notify("WATCHDOG=1")
