"""GPS position, track and driven distance.

To keep the track clean and SD card writes low:

* while driving, a point is stored at most every ``_MOVING_INTERVAL`` seconds;
* while parked, GPS jitter is ignored and one heartbeat point is stored every
  ``_PARKED_INTERVAL`` seconds;
* distance only accumulates while the van is actually moving.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from smartify.db import transaction
from smartify.hardware import GpsFix, GpsReceiver, HardwareError

_MOVING_SPEED_KMH = 3.0
_MIN_MOVE_METERS = 15.0
_MOVING_INTERVAL = 10
_PARKED_INTERVAL = 600
_FIX_TIMEOUT = 5.0

Status = Literal["disabled", "no_device", "no_fix", "ok"]


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance (haversine) in metres."""
    r = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


@dataclass(frozen=True)
class GpsState:
    status: Status
    fix: GpsFix | None
    fix_at: int | None
    error: str | None


class GpsService:
    def __init__(
        self,
        receiver: GpsReceiver | None,
        db_path: Path,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._receiver = receiver
        self._db_path = db_path
        self._clock = clock
        self._lock = threading.Lock()
        self._fix: GpsFix | None = None
        self._fix_at: int | None = None
        self._error: str | None = None
        self._connected = False
        self._last_stored: tuple[int, float, float] | None = None
        self._last_moving_point: tuple[float, float] | None = None

    @property
    def enabled(self) -> bool:
        return self._receiver is not None

    def poll(self) -> None:
        """Wait for one fix and process it. Called in a loop by the GPS worker."""
        if self._receiver is None:
            return
        try:
            fix = self._receiver.read_fix(_FIX_TIMEOUT)
        except HardwareError as exc:
            with self._lock:
                self._connected, self._error = False, str(exc)
            self._clock_sleep(2)
            return
        with self._lock:
            self._connected, self._error = True, None
        if fix is not None:
            self.process(fix)

    def _clock_sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def process(self, fix: GpsFix) -> None:
        now = int(self._clock())
        with self._lock:
            self._fix, self._fix_at = fix, now
            moving = (fix.speed_kmh or 0.0) >= _MOVING_SPEED_KMH

            if moving:
                if self._last_moving_point is not None:
                    meters = distance_m(*self._last_moving_point, fix.lat, fix.lon)
                    if meters >= _MIN_MOVE_METERS:
                        self._add_distance(meters / 1000.0, now)
                        self._last_moving_point = (fix.lat, fix.lon)
                else:
                    self._last_moving_point = (fix.lat, fix.lon)
            else:
                self._last_moving_point = None

            last = self._last_stored
            interval = _MOVING_INTERVAL if moving else _PARKED_INTERVAL
            if last is None or now - last[0] >= interval:
                self._store(fix, now)
                self._last_stored = (now, fix.lat, fix.lon)

    def _store(self, fix: GpsFix, now: int) -> None:
        with transaction(self._db_path) as conn:
            conn.execute(
                "INSERT INTO gps_fixes (lat, lon, speed_kmh, course, altitude_m, satellites, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (fix.lat, fix.lon, fix.speed_kmh, fix.course, fix.altitude_m, fix.satellites, now),
            )

    def _add_distance(self, km: float, now: int) -> None:
        day = time.strftime("%Y-%m-%d", time.localtime(now))
        with transaction(self._db_path) as conn:
            conn.execute(
                "INSERT INTO gps_distance_daily (day, distance_km, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT (day) DO UPDATE SET distance_km = distance_km + excluded.distance_km, "
                "updated_at = excluded.updated_at",
                (day, km, now),
            )

    # --- queries ---------------------------------------------------------

    def state(self) -> GpsState:
        with self._lock:
            if self._receiver is None:
                return GpsState("disabled", None, None, None)
            if not self._connected and self._error:
                return GpsState("no_device", self._fix, self._fix_at, self._error)
            fresh = self._fix_at is not None and self._clock() - self._fix_at < 30
            return GpsState("ok" if fresh else "no_fix", self._fix, self._fix_at, self._error)

    def track(self, since: int) -> list[dict]:
        with transaction(self._db_path) as conn:
            rows = conn.execute(
                "SELECT created_at, lat, lon, speed_kmh FROM gps_fixes "
                "WHERE created_at >= ? ORDER BY created_at",
                (since,),
            ).fetchall()
        return [dict(row) for row in rows]

    def distance_by_day(self, days: int = 30) -> list[dict]:
        with transaction(self._db_path) as conn:
            rows = conn.execute(
                "SELECT day, round(distance_km, 2) AS distance_km FROM gps_distance_daily "
                "ORDER BY day DESC LIMIT ?",
                (days,),
            ).fetchall()
        return [dict(row) for row in rows]

    def total_distance_km(self) -> float:
        with transaction(self._db_path) as conn:
            total = conn.execute("SELECT COALESCE(SUM(distance_km), 0) FROM gps_distance_daily")
            return round(total.fetchone()[0], 2)
