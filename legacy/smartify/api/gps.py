"""
GPS tracking API endpoints.
"""
import math
import time
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, Request, Header
from fastapi.responses import JSONResponse

from smartify import state
from smartify.auth import require_auth
from smartify.db import (
    db_query_gps_since,
    db_query_gps_between,
    db_sum_gps_distance_between,
    db_sum_gps_distance_all,
)


router = APIRouter(tags=["gps"])


@router.get("/api/gps/current")
def api_gps_current(request: Request, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    err = require_auth(request, x_api_key)
    if err:
        return err
    return JSONResponse(state._gps_latest)


@router.get("/api/gps/track")
def api_gps_track(
    request: Request,
    hours: Optional[int] = None,
    minutes: Optional[int] = None,
    limit: int = 2000,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    err = require_auth(request, x_api_key)
    if err:
        return err

    now = int(time.time())
    if minutes is not None:
        since = now - int(minutes) * 60
    elif hours is not None:
        since = now - int(hours) * 3600
    else:
        since = now - 24 * 3600

    limit = max(1, min(int(limit), 50000))
    rows = db_query_gps_since(since, limit=limit)
    return JSONResponse({"since": since, "now": now, "rows": rows})


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _compute_distance_and_altitude(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    distance_km = 0.0
    prev = None
    altitudes = []

    for r in rows:
        lat = r.get("lat")
        lon = r.get("lon")
        if lat is None or lon is None:
            continue
        if prev is not None:
            distance_km += _haversine_km(prev["lat"], prev["lon"], lat, lon)
        prev = {"lat": lat, "lon": lon}
        if r.get("altitude_m") is not None:
            altitudes.append(r["altitude_m"])

    if altitudes:
        alt_min = min(altitudes)
        alt_max = max(altitudes)
        alt_avg = sum(altitudes) / len(altitudes)
    else:
        alt_min = alt_max = alt_avg = None

    return {
        "distance_km": round(distance_km, 3),
        "altitude_min_m": alt_min,
        "altitude_max_m": alt_max,
        "altitude_avg_m": alt_avg,
        "points": len(rows),
    }


@router.get("/api/gps/stats/summary")
def api_gps_stats_summary(
    request: Request,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    max_points: int = 50000,
):
    err = require_auth(request, x_api_key)
    if err:
        return err

    now = int(time.time())
    periods = {
        "day": now - 24 * 3600,
        "week": now - 7 * 24 * 3600,
        "month": now - 30 * 24 * 3600,
        "year": now - 365 * 24 * 3600,
        "total": 0,
    }

    summary: Dict[str, Any] = {"now": now, "periods": {}}
    today = time.strftime("%Y-%m-%d", time.localtime(now))
    for name, since in periods.items():
        if name == "total":
            distance_km = db_sum_gps_distance_all()
            rows = db_query_gps_between(0, now, limit=max_points)
        else:
            start_date = time.strftime("%Y-%m-%d", time.localtime(since))
            distance_km = db_sum_gps_distance_between(start_date, today)
            rows = db_query_gps_between(since, now, limit=max_points)

        if len(rows) > max_points:
            step = max(1, math.ceil(len(rows) / max_points))
            rows = rows[::step]
        stats = _compute_distance_and_altitude(rows)
        stats["distance_km"] = round(distance_km, 3)
        summary["periods"][name] = {
            "since": since,
            **stats,
        }

    return JSONResponse(summary)
