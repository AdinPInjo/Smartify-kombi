"""Alerts: watch the van and send a notification when something needs attention.

Each check reports whether its alert is *active*. A message is sent when an
alert becomes active and has stayed so for a short confirmation time (so a
single odd reading sends nothing), then not again until it has cleared, unless
``repeat_hours`` asks for reminders. Thresholds have hysteresis: "battery below
20 %" only clears above 25 %, so a value hovering at the limit does not send a
message every few minutes.

Active alerts are stored, so a restart does not send them again.

Not every alert is a level: *departure* (the van drives off after standing
still) fires on the moment it happens, and the *frost* forecast once per evening.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from smartify.db import transaction
from smartify.services import forecast as energy_forecast
from smartify.services.notify import (
    NotificationService,
    NotificationSettings,
    Priority,
    in_window,
)

log = logging.getLogger(__name__)

_CONFIRM_SECONDS = 120
_FAULT_CONFIRM_SECONDS = 300
_NOT_CHARGING_CONFIRM_SECONDS = 600
_DRIVING_KMH = 30.0
_FORECAST_EVERY = 1800
_FROST_FROM_HOUR = 16  # the frost warning goes out in the late afternoon / evening
_FROST_UNTIL_HOUR = 23
_ENERGY_ALERT_GAP = 12 * 3600


@dataclass
class _State:
    active: bool
    since: int
    last_sent_at: int | None


def osm_link(lat: float, lon: float) -> str:
    return (
        f"https://www.openstreetmap.org/?mlat={lat:.5f}&mlon={lon:.5f}#map=16/{lat:.5f}/{lon:.5f}"
    )


def _hhmm(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M")


def _duration(seconds: float) -> str:
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes} min"
    hours = minutes // 60
    if hours < 48:
        return f"{hours} h {minutes % 60} min" if minutes % 60 else f"{hours} h"
    return f"{hours // 24} days"


class AlertService:
    def __init__(
        self,
        ctx: Any,
        notifications: NotificationService,
        db_path: Path,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """``ctx`` is the AppContext (climate, water, energy, gps, relays, weather)."""
        self._ctx = ctx
        self._notify = notifications
        self._db_path = db_path
        self._clock = clock
        self._lock = threading.Lock()
        self._states: dict[str, _State] | None = None
        self._pending: dict[str, float] = {}
        self._was_parked_since: int | None = None
        self._forecast: energy_forecast.Forecast | None = None
        self._forecast_at = 0.0

    # --- state bookkeeping ---------------------------------------------------

    def _load(self) -> dict[str, _State]:
        if self._states is None:
            with transaction(self._db_path) as conn:
                rows = conn.execute("SELECT * FROM alert_state").fetchall()
            self._states = {
                row["key"]: _State(bool(row["active"]), row["since"], row["last_sent_at"])
                for row in rows
            }
        return self._states

    def _store(self, key: str, state: _State) -> None:
        self._load()[key] = state
        with transaction(self._db_path) as conn:
            conn.execute(
                "INSERT INTO alert_state (key, active, since, last_sent_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (key) DO UPDATE SET active = excluded.active, since = excluded.since, "
                "last_sent_at = excluded.last_sent_at",
                (key, int(state.active), state.since, state.last_sent_at),
            )

    def is_active(self, key: str) -> bool:
        state = self._load().get(key)
        return bool(state and state.active)

    def _level(
        self,
        key: str,
        active: bool | None,
        title: str,
        message: str,
        settings: NotificationSettings,
        priority: Priority = "default",
        confirm: float = _CONFIRM_SECONDS,
        click_url: str | None = None,
    ) -> None:
        """Track a level alert. ``active=None`` means unknown right now: change nothing."""
        if active is None:
            self._pending.pop(key, None)
            return
        now = self._clock()
        state = self._load().get(key)
        if not active:
            self._pending.pop(key, None)
            if state and state.active:
                self._store(key, _State(False, int(now), state.last_sent_at))
            return
        if state and state.active:
            repeat = settings.repeat_hours * 3600
            if repeat and state.last_sent_at and now - state.last_sent_at >= repeat:
                self._notify.notify(key, f"Still: {title}", message, priority, click_url)
                self._store(key, _State(True, state.since, int(now)))
            return
        started = self._pending.setdefault(key, now)
        if now - started < confirm:
            return
        self._pending.pop(key, None)
        self._notify.notify(key, title, message, priority, click_url)
        self._store(key, _State(True, int(started), int(now)))

    # --- checks -------------------------------------------------------------------

    def check(self) -> None:
        """Called by the alerts worker every few seconds."""
        with self._lock:
            settings = self._notify.settings()
            for name, check in (
                ("battery", self._battery),
                ("climate", self._climate),
                ("water", self._water),
                ("faults", self._faults),
                ("cutoffs", self._cutoffs),
                ("departure", self._departure),
                ("frost", self._frost),
                ("energy forecast", self._energy_forecast),
                ("heater", self._heater),
            ):
                try:
                    check(settings)
                except Exception:
                    log.exception("Alert check %s failed", name)

    def _heater(self, settings: NotificationSettings) -> None:
        """Faults the diesel heater reports. Always on: a fault or CO alarm matters."""
        for heater in self._ctx.heaters.list():
            status = heater["status"]
            fault = status["error"] if status else None
            carbon = bool(fault and ("CO" in fault or "carbon" in fault.lower()))
            self._level(
                f"heater_fault:{heater['id']}",
                None if status is None else fault is not None,
                f"{heater['name']}: {'carbon monoxide alarm' if carbon else 'fault'}",
                (
                    f"The heater reports: {fault}. Ventilate the van now "
                    "and leave it if you feel unwell."
                    if carbon
                    else f"The heater reports: {fault}."
                )
                if fault
                else "",
                settings,
                "urgent" if carbon else "high",
                confirm=0 if carbon else 30,
            )

    def _battery(self, settings: NotificationSettings) -> None:
        alerts = settings.alerts
        battery = self._ctx.energy.summary().get("battery") or {}
        soc, current = battery.get("soc"), battery.get("current")
        if alerts.battery_low.enabled:
            limit = alerts.battery_low.threshold
            active = None
            if soc is not None:
                active = soc < (limit + 5 if self.is_active("battery_low") else limit)
            self._level(
                "battery_low",
                active,
                "Battery low",
                f"House battery at {soc:.0f} % (alert below {limit:.0f} %). "
                "Drive, find sun or plug in."
                if soc is not None
                else "",
                settings,
                "high",
            )
        if alerts.battery_not_charging.enabled:
            gps = self._ctx.gps.state()
            driving = (
                gps.status == "ok"
                and not gps.parked
                and gps.fix is not None
                and (gps.fix.speed_kmh or 0) >= _DRIVING_KMH
            )
            active = None if current is None else driving and current <= 0.5
            self._level(
                "battery_not_charging",
                active,
                "Battery not charging while driving",
                f"Driving for 10 minutes, but the house battery is at {current:+.1f} A. "
                "Check the DC-DC charger (Orion) and its fuse."
                if current is not None
                else "",
                settings,
                "high",
                confirm=_NOT_CHARGING_CONFIRM_SECONDS,
            )

    def _climate_value(self, sensor: str) -> tuple[str, float | None]:
        snapshots = self._ctx.climate.snapshots()
        chosen = next((s for s in snapshots if s.sensor == sensor), None) if sensor else None
        if chosen is None and not sensor and snapshots:
            chosen = snapshots[0]
        if chosen is None or chosen.status != "ready":
            return sensor, None
        return chosen.sensor, chosen.temperature_c

    def _climate(self, settings: NotificationSettings) -> None:
        cold, hot = settings.alerts.cold_inside, settings.alerts.hot_inside
        if cold.enabled:
            name, temp = self._climate_value(cold.sensor)
            limit = cold.threshold
            active = None
            if temp is not None:
                active = temp < (limit + 1 if self.is_active("cold_inside") else limit)
            self._level(
                "cold_inside",
                active,
                "Cold in the van",
                f"{name.capitalize()} is {temp:.1f} °C (alert below {limit:g} °C). "
                "Water pipes can freeze: switch the heater on or drain the water."
                if temp is not None
                else "",
                settings,
                "urgent",
            )
        if hot.enabled:
            name, temp = self._climate_value(hot.sensor)
            limit = hot.threshold
            active = None
            if temp is not None:
                active = temp > (limit - 1 if self.is_active("hot_inside") else limit)
            self._level(
                "hot_inside",
                active,
                "Hot in the van",
                f"{name.capitalize()} is {temp:.1f} °C (alert above {limit:g} °C). "
                "Too hot for pets: open the roof vent or switch the fan on."
                if temp is not None
                else "",
                settings,
                "urgent",
            )

    def _water(self, settings: NotificationSettings) -> None:
        alert = settings.alerts.water_low
        if not alert.enabled:
            return
        reading = self._ctx.water.current()
        level = reading.level_percent if reading.ok else None
        active = None
        if level is not None:
            active = level < (
                alert.threshold + 5 if self.is_active("water_low") else alert.threshold
            )
        self._level(
            "water_low",
            active,
            "Water tank almost empty",
            f"Fresh water at {level} %. Time to fill up." if level is not None else "",
            settings,
        )

    def _faults(self, settings: NotificationSettings) -> None:
        if not settings.alerts.sensor_fault.enabled:
            return
        for snap in self._ctx.climate.snapshots():
            self._level(
                f"sensor:{snap.sensor}",
                snap.status == "stale" if snap.status != "warming_up" else None,
                f"Sensor '{snap.sensor}' not responding",
                f"No reading from the {snap.sensor} temperature sensor"
                + (f": {snap.last_error}" if snap.last_error else ".")
                + " Rules that use it switch their relay off.",
                settings,
                confirm=_FAULT_CONFIRM_SECONDS,
            )
        gps = self._ctx.gps.state()
        if gps.status != "disabled":
            self._level(
                "sensor:gps",
                gps.status == "no_device",
                "GPS not connected",
                f"The GPS receiver is not responding ({gps.error or 'no data'}). "
                "The route is not recorded and theft alerts cannot work.",
                settings,
                confirm=_FAULT_CONFIRM_SECONDS,
            )
        for device in self._ctx.energy.devices():
            self._level(
                f"sensor:victron:{device.device}",
                device.stale,
                f"Victron '{device.device}' not reporting",
                f"No Bluetooth data from {device.device} ({device.model or device.kind}) "
                "for a while. Is it switched on and in range?",
                settings,
                confirm=_FAULT_CONFIRM_SECONDS,
            )

    def _cutoffs(self, settings: NotificationSettings) -> None:
        if not settings.alerts.relay_cutoff.enabled:
            return
        tripped = self._ctx.relays.tripped_ids
        for relay in self._ctx.relays.list():
            name = relay.label or relay.name
            self._level(
                f"cutoff:{relay.id}",
                relay.id in tripped,
                f"{name.capitalize()} switched off for safety",
                f"The temperature cutoff of {name} tripped "
                f"({relay.cutoff_sensor} above {relay.cutoff_max_c} °C).",
                settings,
                "urgent",
                confirm=0,
            )

    def _departure(self, settings: NotificationSettings) -> None:
        alert = settings.alerts.departure
        state = self._ctx.gps.state()
        parked_since, self._was_parked_since = (
            self._was_parked_since,
            state.parked_since if state.parked else None,
        )
        if state.parked or parked_since is None or state.status != "ok" or state.fix is None:
            return
        # The van was parked at the last check and is moving now.
        now = self._clock()
        stood = now - parked_since
        if not alert.enabled or stood < alert.after_minutes * 60:
            return
        if alert.paused_until and now < alert.paused_until:
            log.info("Van moving, departure alert paused")
            return
        if alert.night_only and not in_window(
            datetime.fromtimestamp(now), alert.night_from, alert.night_to
        ):
            return
        fix = state.fix
        speed = f" Speed now {fix.speed_kmh:.0f} km/h." if fix.speed_kmh else ""
        self._notify.notify(
            "departure",
            "The van is moving!",
            f"It started moving at {_hhmm(now)} after standing still for {_duration(stood)}."
            f"{speed} Not you? Open the map. If it is you, you can pause these alerts "
            "in the dashboard.",
            "urgent",
            osm_link(fix.lat, fix.lon),
        )

    def _frost(self, settings: NotificationSettings) -> None:
        alert = settings.alerts.frost_forecast
        if not alert.enabled:
            return
        now = self._clock()
        local = datetime.fromtimestamp(now)
        if not _FROST_FROM_HOUR <= local.hour < _FROST_UNTIL_HOUR:
            return
        state = self._load().get("frost_forecast")
        if (
            state
            and state.last_sent_at
            and datetime.fromtimestamp(state.last_sent_at).date() == local.date()
        ):
            return
        until = (local + timedelta(days=1)).replace(hour=10, minute=0, second=0).timestamp()
        night = [
            h
            for h in self._ctx.weather.hourly()
            if now <= h["ts"] <= until and h.get("temperature_c") is not None
        ]
        if not night:
            return
        coldest = min(night, key=lambda h: h["temperature_c"])
        if coldest["temperature_c"] > alert.threshold:
            return
        self._notify.notify(
            "frost_forecast",
            "Frost tonight",
            f"Down to {coldest['temperature_c']:.0f} °C around {_hhmm(coldest['ts'])}. "
            "Keep the heater on low or drain the water system.",
            "high",
        )
        self._store("frost_forecast", _State(False, int(now), int(now)))

    # --- energy forecast --------------------------------------------------------------

    def forecast(self, refresh: bool = False) -> energy_forecast.Forecast:
        now = self._clock()
        if refresh or self._forecast is None or now - self._forecast_at >= _FORECAST_EVERY:
            settings = self._notify.settings().alerts.energy_forecast
            self._forecast = energy_forecast.compute(
                self._ctx.energy.summary(),
                self._ctx.energy.history(int(now) - 24 * 3600),
                self._ctx.weather.hourly(),
                now,
                settings.battery_capacity_ah,
                settings.solar_peak_w,
            )
            self._forecast_at = now
        return self._forecast

    def _energy_forecast(self, settings: NotificationSettings) -> None:
        alert = settings.alerts.energy_forecast
        if not alert.enabled:
            return
        result = self.forecast()
        if not result.available or result.min_soc is None or result.min_at is None:
            return
        state = self._load().get("energy_forecast")
        now = self._clock()
        if state and state.active:
            if result.min_soc >= alert.threshold + 5:
                self._store("energy_forecast", _State(False, int(now), state.last_sent_at))
            return
        if result.min_soc >= alert.threshold:
            return
        if state and state.last_sent_at and now - state.last_sent_at < _ENERGY_ALERT_GAP:
            return
        when = datetime.fromtimestamp(result.min_at)
        day = "today" if when.date() == datetime.fromtimestamp(now).date() else "tomorrow"
        sun = (result.solar_wh_24h or 0) / 1000
        self._notify.notify(
            "energy_forecast",
            "Battery forecast",
            f"The battery will be down to about {result.min_soc:.0f} % by "
            f"{when:%H:%M} {day} (now {result.soc_now:.0f} %, using ~{result.load_w:.0f} W, "
            f"{sun:.1f} kWh of sun expected in 24 h). Plan a drive or a campsite with power.",
        )
        self._store("energy_forecast", _State(True, int(now), int(now)))
