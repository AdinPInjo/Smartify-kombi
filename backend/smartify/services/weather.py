"""Outside weather for the van's position, from Open-Meteo (free, no API key).

Needs a GPS position and internet. Refreshes every ``weather_interval_seconds``,
or sooner after the van has moved more than ``_REFRESH_DISTANCE_KM``.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from smartify.db import transaction
from smartify.services.gps import GpsService, distance_m

log = logging.getLogger(__name__)

API_URL = "https://api.open-meteo.com/v1/forecast"
_REFRESH_DISTANCE_KM = 5.0
_RETRY_SECONDS = 300

Fetcher = Callable[[str], dict[str, Any]]


def _http_get_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "smartify-kombi"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def build_url(lat: float, lon: float) -> str:
    params = {
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code",
        "hourly": "temperature_2m,shortwave_radiation",
        "forecast_days": "5",
        "timezone": "auto",
        # Unix timestamps, so hourly values line up with the Pi's clock in any time zone.
        "timeformat": "unixtime",
    }
    return f"{API_URL}?{urllib.parse.urlencode(params)}"


def _day(value: Any, offset: int) -> str:
    """Daily ``time`` is a Unix timestamp with ``timeformat=unixtime``; show it as a date."""
    if isinstance(value, int | float):
        return time.strftime("%Y-%m-%d", time.gmtime(value + offset))
    return str(value)


def parse_hourly(data: dict[str, Any]) -> list[dict[str, Any]]:
    """``[{"ts", "temperature_c", "radiation_w_m2"}]`` from the hourly forecast."""
    hourly = data.get("hourly") or {}
    times = hourly.get("time") or []
    temps = hourly.get("temperature_2m") or []
    radiation = hourly.get("shortwave_radiation") or []
    return [
        {
            "ts": int(ts),
            "temperature_c": temps[i] if i < len(temps) else None,
            "radiation_w_m2": radiation[i] if i < len(radiation) else None,
        }
        for i, ts in enumerate(times)
        if isinstance(ts, int | float)
    ]


def parse_response(data: dict[str, Any]) -> dict[str, Any]:
    current = data.get("current", {})
    daily = data.get("daily", {})
    offset = int(data.get("utc_offset_seconds") or 0)
    days = [
        {
            "date": _day(date, offset),
            "temperature_max": daily["temperature_2m_max"][i],
            "temperature_min": daily["temperature_2m_min"][i],
            "precipitation_mm": daily["precipitation_sum"][i],
            "weather_code": daily["weather_code"][i],
        }
        for i, date in enumerate(daily.get("time", []))
    ]
    return {
        "temperature_c": current.get("temperature_2m"),
        "humidity": current.get("relative_humidity_2m"),
        "wind_kmh": current.get("wind_speed_10m"),
        "weather_code": current.get("weather_code"),
        "forecast": days,
    }


class WeatherService:
    def __init__(
        self,
        gps: GpsService,
        db_path: Path,
        interval_seconds: int,
        fetcher: Fetcher = _http_get_json,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._gps = gps
        self._db_path = db_path
        self._interval = interval_seconds
        self._fetch = fetcher
        self._clock = clock
        self._lock = threading.Lock()
        self._latest: dict[str, Any] | None = None
        self._latest_at: int | None = None
        self._latest_position: tuple[float, float] | None = None
        self._hourly: list[dict[str, Any]] = []
        self._next_attempt = 0.0
        self._error: str | None = None

    def _position(self) -> tuple[float, float] | None:
        fix = self._gps.state().fix
        if fix is not None:
            return fix.lat, fix.lon
        with transaction(self._db_path) as conn:
            row = conn.execute(
                "SELECT lat, lon FROM gps_fixes ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        return (row["lat"], row["lon"]) if row else None

    def refresh_if_due(self) -> None:
        position = self._position()
        if position is None:
            with self._lock:
                self._error = "no GPS position yet"
            return
        now = self._clock()
        with self._lock:
            moved_km = (
                distance_m(*self._latest_position, *position) / 1000.0
                if self._latest_position
                else 0.0
            )
            due = self._latest_at is None or now - self._latest_at >= self._interval
            if not (due or moved_km >= _REFRESH_DISTANCE_KM) or now < self._next_attempt:
                return
        try:
            data = self._fetch(build_url(*position))
            weather = parse_response(data)
            hourly = parse_hourly(data)
        except Exception as exc:  # network errors are routine in a van
            with self._lock:
                self._error = f"weather unavailable: {exc}"
                self._next_attempt = now + _RETRY_SECONDS
            log.info("Weather fetch failed: %s", exc)
            return
        with self._lock:
            self._latest, self._latest_at = weather, int(now)
            self._latest_position, self._error = position, None
            self._hourly = hourly
        with transaction(self._db_path) as conn:
            conn.execute(
                "INSERT INTO weather_samples (lat, lon, temperature_c, humidity, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (*position, weather["temperature_c"], weather["humidity"], int(now)),
            )

    def current(self) -> dict[str, Any]:
        with self._lock:
            return {
                "available": self._latest is not None,
                "updated_at": self._latest_at,
                "error": self._error,
                **(self._latest or {}),
            }

    def hourly(self) -> list[dict[str, Any]]:
        """Hourly forecast (temperature, solar radiation) from the last fetch.

        Kept out of :meth:`current`, which is uploaded to the remote dashboard
        every minute and should stay small on mobile data.
        """
        with self._lock:
            return list(self._hourly)

    def history(self, since: int) -> list[dict]:
        with transaction(self._db_path) as conn:
            rows = conn.execute(
                "SELECT created_at, temperature_c, humidity FROM weather_samples "
                "WHERE created_at >= ? ORDER BY created_at",
                (since,),
            ).fetchall()
        return [dict(row) for row in rows]
