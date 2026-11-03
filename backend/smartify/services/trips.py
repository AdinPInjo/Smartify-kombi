"""Travel log: every place the van stood still for an hour or more.

A stop starts when the GPS has reported *parked* for ``STOP_MIN_SECONDS`` (its
arrival time is when the van stopped) and ends once a few good fixes in a row
are more than ``_LEAVE_METERS`` away. A service restart or a lost GPS signal
does not end a stop.

Place names come from OpenStreetMap (Nominatim) when the van is online, and are
filled in later otherwise.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from smartify.db import transaction
from smartify.services.gps import GpsService, distance_m

log = logging.getLogger(__name__)

STOP_MIN_SECONDS = 3600
_LEAVE_METERS = 250.0
_LEAVE_FIXES = 3
_GEOCODE_RETRY_SECONDS = 600
_NOMINATIM = "https://nominatim.openstreetmap.org/reverse"
_USER_AGENT = "smartify-kombi/1 (https://github.com/AdinPInjo/Smartify-kombi)"

Geocoder = Callable[[float, float], tuple[str | None, str | None]]


def nominatim(lat: float, lon: float) -> tuple[str | None, str | None]:
    """Reverse geocode to (place, country). Nominatim allows 1 request/s; we send far fewer."""
    params = urllib.parse.urlencode(
        {
            "lat": f"{lat:.5f}",
            "lon": f"{lon:.5f}",
            "format": "jsonv2",
            "zoom": 14,
            "accept-language": "en",
        }
    )
    request = urllib.request.Request(f"{_NOMINATIM}?{params}", headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=10) as response:
        data = json.load(response)
    return place_from(data)


def place_from(data: dict[str, Any]) -> tuple[str | None, str | None]:
    address = data.get("address") or {}
    for key in ("village", "town", "city", "hamlet", "suburb", "municipality", "county", "state"):
        if address.get(key):
            return address[key], address.get("country")
    name = data.get("name") or (data.get("display_name") or "").split(",")[0]
    return (name or None), address.get("country")


def nights(arrived_at: int, left_at: int) -> int:
    """Nights spent: how many times the van was there at 03:00 local time."""
    start = datetime.fromtimestamp(arrived_at)
    end = datetime.fromtimestamp(left_at)
    night = start.replace(hour=3, minute=0, second=0, microsecond=0)
    if night < start:
        night += timedelta(days=1)
    count = 0
    while night <= end:
        count += 1
        night += timedelta(days=1)
    return count


class TripService:
    def __init__(
        self,
        gps: GpsService,
        db_path: Path,
        geocoder: Geocoder = nominatim,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._gps = gps
        self._db_path = db_path
        self._geocode = geocoder
        self._clock = clock
        self._far_fixes = 0
        self._next_geocode = 0.0

    def _open_stop(self) -> Any:
        with transaction(self._db_path) as conn:
            return conn.execute(
                "SELECT * FROM stops WHERE left_at IS NULL ORDER BY arrived_at DESC LIMIT 1"
            ).fetchone()

    def tick(self) -> None:
        """Called by the trips worker every half minute."""
        now = int(self._clock())
        state = self._gps.state()
        stop = self._open_stop()
        fix = state.fix if state.status == "ok" else None

        if stop is not None and fix is not None:
            far = distance_m(stop["lat"], stop["lon"], fix.lat, fix.lon) > _LEAVE_METERS
            self._far_fixes = self._far_fixes + 1 if far else 0
            if self._far_fixes >= _LEAVE_FIXES:
                # Left. Already parked elsewhere? Then it left before it stopped there.
                left = min(now, state.parked_since) if state.parked and state.parked_since else now
                with transaction(self._db_path) as conn:
                    conn.execute("UPDATE stops SET left_at = ? WHERE id = ?", (left, stop["id"]))
                log.info("Left stop %s", stop["place"] or f"{stop['lat']:.4f},{stop['lon']:.4f}")
                stop, self._far_fixes = None, 0

        if (
            stop is None
            and fix is not None
            and state.parked
            and state.parked_since is not None
            and now - state.parked_since >= STOP_MIN_SECONDS
        ):
            with transaction(self._db_path) as conn:
                conn.execute(
                    "INSERT INTO stops (lat, lon, arrived_at, odometer_km) VALUES (?, ?, ?, ?)",
                    (fix.lat, fix.lon, state.parked_since, self._gps.total_distance_km()),
                )
            log.info("New stop at %.5f, %.5f", fix.lat, fix.lon)

        self._fill_place_names()

    def _fill_place_names(self) -> None:
        now = self._clock()
        if now < self._next_geocode:
            return
        with transaction(self._db_path) as conn:
            row = conn.execute(
                "SELECT id, lat, lon FROM stops WHERE place IS NULL "
                "ORDER BY arrived_at DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return
        try:
            place, country = self._geocode(row["lat"], row["lon"])
        except Exception as exc:  # offline is normal in a van
            self._next_geocode = now + _GEOCODE_RETRY_SECONDS
            log.debug("Place name lookup failed: %s", exc)
            return
        self._next_geocode = now + 2  # be gentle with the free service
        with transaction(self._db_path) as conn:
            conn.execute(
                "UPDATE stops SET place = ?, country = ? WHERE id = ?",
                (place or f"{row['lat']:.3f}, {row['lon']:.3f}", country, row["id"]),
            )

    def stops(self, since: int = 0, limit: int = 200) -> list[dict[str, Any]]:
        """Newest first, with nights spent and km driven from the stop before."""
        now = int(self._clock())
        with transaction(self._db_path) as conn:
            rows = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM stops ORDER BY arrived_at DESC LIMIT ?", (limit + 1,)
                )
            ]
        result = []
        for i, row in enumerate(rows[:limit]):
            if (row["left_at"] or now) < since:
                break
            previous = rows[i + 1] if i + 1 < len(rows) else None
            end = row["left_at"] or now
            result.append(
                {
                    **row,
                    "here_now": row["left_at"] is None,
                    "nights": nights(row["arrived_at"], end),
                    "duration_seconds": end - row["arrived_at"],
                    "km_from_previous": round(row["odometer_km"] - previous["odometer_km"], 1)
                    if previous
                    else None,
                }
            )
        return result
