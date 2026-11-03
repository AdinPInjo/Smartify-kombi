"""GPS position, track and driven distance.

To keep the track clean and SD card writes low:

* while driving, a point is stored at most every ``_MOVING_INTERVAL`` seconds;
* while parked, GPS jitter is ignored and one heartbeat point is stored every
  ``_PARKED_INTERVAL`` seconds;
* distance only accumulates while the van is actually moving.

With a weak signal a parked van seems to wander tens of metres and the receiver
even reports short bursts of speed. So once the van has stood still for
``_PARK_AFTER_SECONDS`` it is treated as *parked*:

* the reported position is the median of the good fixes while parked, which
  stays put instead of bouncing;
* fixes with poor geometry (high HDOP, few satellites) are left out;
* the van only counts as driving again when good fixes show it really left
  (speed plus distance from the parked spot, or several fast fixes in a row).
"""

from __future__ import annotations

import logging
import math
import statistics
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from smartify.db import transaction
from smartify.hardware import GpsFix, GpsReceiver, HardwareError
from smartify.services.conditions import MetricValue, SensorIssue

log = logging.getLogger(__name__)

_MOVING_SPEED_KMH = 3.0
_MIN_MOVE_METERS = 15.0
_MAX_PLAUSIBLE_KMH = 250.0
_MOVING_INTERVAL = 10
_PARKED_INTERVAL = 600
_FIX_TIMEOUT = 5.0

# Parked smoothing
_PARK_AFTER_SECONDS = 20  # standing still this long = parked
_PARKED_RADIUS_M = 30.0  # jitter inside this radius is ignored while parked
_LEAVE_FAST_FIXES = 3  # good fast fixes in a row needed to leave the parked spot
_RELOCATE_FIXES = 5  # good fixes far from the spot in a row: moved slowly, re-anchor
_STILL_WINDOW = 600  # most recent good fixes used for the parked median (~10 min at 1 Hz)
_MAX_HDOP = 4.0  # worse geometry than this is not trusted while parked
_MIN_SATELLITES = 4

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
    parked: bool = False
    """True while the van stands still and ``fix`` is the smoothed parked position."""
    parked_since: int | None = None
    """When the van stopped at the current parked spot."""


def _good(fix: GpsFix) -> bool:
    """Is the fix geometry good enough to move the parked position or to leave it?"""
    if fix.hdop is not None and fix.hdop > _MAX_HDOP:
        return False
    if fix.satellites is not None and fix.satellites < _MIN_SATELLITES:
        return False
    return True


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
        self._last_moving_point: tuple[float, float, int] | None = None
        # Parked smoothing state (guarded by _lock)
        self._still: deque[tuple[float, float, int]] = deque(maxlen=_STILL_WINDOW)
        self._parked = False
        self._parked_since: int | None = None
        self._started_at = clock()
        self._anchor: tuple[float, float] | None = None
        self._fast_count = 0
        self._far_count = 0

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

    def _median_anchor(self) -> tuple[float, float]:
        return (
            statistics.median(p[0] for p in self._still),
            statistics.median(p[1] for p in self._still),
        )

    def _leave_parked(self) -> None:
        self._parked = False
        self._parked_since = None
        self._anchor = None
        self._still.clear()
        self._fast_count = self._far_count = 0

    def _classify(self, fix: GpsFix, now: int) -> tuple[bool, GpsFix]:
        """Update the parked state with one fix. Returns (moving, fix to report and store)."""
        fast = (fix.speed_kmh or 0.0) >= _MOVING_SPEED_KMH
        good = _good(fix)

        if self._parked and self._anchor is not None:
            anchor_lat, anchor_lon = self._anchor
            meters = distance_m(anchor_lat, anchor_lon, fix.lat, fix.lon)
            self._fast_count = self._fast_count + 1 if (fast and good) else 0
            far = good and meters > 3 * _PARKED_RADIUS_M
            self._far_count = self._far_count + 1 if far else 0

            left = meters > _PARKED_RADIUS_M or self._fast_count >= _LEAVE_FAST_FIXES
            if good and fast and left:
                # Really driving off: start the driven segment at the parked spot.
                since = self._still[-1][2] if self._still else now - 1
                self._leave_parked()
                self._last_moving_point = (anchor_lat, anchor_lon, since)
                speed = fix.speed_kmh or 0.0
                log.info("Leaving parked spot (%.0f m away, %.0f km/h)", meters, speed)
                return True, fix
            if self._far_count >= _RELOCATE_FIXES:
                # Moved slowly (e.g. re-parked) without a speed reading: re-anchor here.
                log.info("Parked position re-anchored %.0f m away", meters)
                self._still.clear()
                self._still.append((fix.lat, fix.lon, now))
                self._anchor = (fix.lat, fix.lon)
                self._parked_since = now
                self._far_count = 0
            elif good and meters <= 2 * _PARKED_RADIUS_M:
                self._still.append((fix.lat, fix.lon, now))
                self._anchor = self._median_anchor()
            lat, lon = self._anchor
            return False, replace(fix, lat=lat, lon=lon, speed_kmh=0.0, course=None)

        if fast:
            self._still.clear()
            return True, fix
        if good:
            self._still.append((fix.lat, fix.lon, now))
        if len(self._still) >= 2 and self._still[-1][2] - self._still[0][2] >= _PARK_AFTER_SECONDS:
            self._parked = True
            self._parked_since = self._still[0][2]
            self._anchor = self._median_anchor()
            self._fast_count = self._far_count = 0
            log.info("Parked: position smoothed from %d fixes", len(self._still))
            lat, lon = self._anchor
            return False, replace(fix, lat=lat, lon=lon, speed_kmh=0.0, course=None)
        return False, fix

    def process(self, fix: GpsFix) -> None:
        now = int(self._clock())
        add_km = 0.0
        store = False
        with self._lock:
            moving, fix = self._classify(fix, now)
            self._fix, self._fix_at = fix, now
            previous = self._last_moving_point

            if previous is not None:
                meters = distance_m(previous[0], previous[1], fix.lat, fix.lon)
                seconds = max(now - previous[2], 1)
                if meters / seconds * 3.6 > _MAX_PLAUSIBLE_KMH:
                    # A bogus fix (multipath, cold start). Restart the segment here.
                    log.info("Ignoring GPS jump of %.0f m in %d s", meters, seconds)
                    self._last_moving_point = (fix.lat, fix.lon, now) if moving else None
                elif meters >= _MIN_MOVE_METERS or not moving:
                    # Count the step; when the van stops, also count the last bit.
                    add_km = meters / 1000.0 if meters >= _MIN_MOVE_METERS else 0.0
                    self._last_moving_point = (fix.lat, fix.lon, now) if moving else None
            elif moving:
                self._last_moving_point = (fix.lat, fix.lon, now)

            last = self._last_stored
            interval = _MOVING_INTERVAL if moving else _PARKED_INTERVAL
            if last is None or now - last[0] >= interval:
                store = True
                self._last_stored = (now, fix.lat, fix.lon)

        # Database writes happen outside the lock so /api/gps never waits on them.
        if add_km:
            self._add_distance(add_km, now)
        if store:
            self._store(fix, now)

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
            status = "ok" if fresh else "no_fix"
            return GpsState(
                status,
                self._fix,
                self._fix_at,
                self._error,
                self._parked,
                self._parked_since if self._parked else None,
            )

    def metric(self, sensor: str, metric: str) -> MetricValue:
        """Value source for rule conditions on ``speed`` (sensor ``gps``), in km/h."""
        state = self.state()
        if state.status == "ok" and state.fix is not None:
            return MetricValue(0.0 if state.parked else float(state.fix.speed_kmh or 0.0))
        if state.fix_at is None and self._clock() - self._started_at < 180:
            return MetricValue(None, SensorIssue.WARMING_UP)  # first fix can take minutes
        return MetricValue(None, SensorIssue.STALE)

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
