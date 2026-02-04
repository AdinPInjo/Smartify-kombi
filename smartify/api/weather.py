"""
Weather API endpoints (Open-Meteo, no API key required).
"""
import json
import time
from typing import Optional
from urllib.request import urlopen
from urllib.error import URLError

from fastapi import APIRouter, Request, Header
from fastapi.responses import JSONResponse

from smartify import state
from smartify.auth import require_auth
from smartify.db import db_insert_weather_sample, db_query_weather_since


router = APIRouter(tags=["weather"])


def _fetch_open_meteo(lat: float, lon: float) -> dict:
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat:.6f}&longitude={lon:.6f}"
        "&current=temperature_2m,weather_code,wind_speed_10m"
        "&temperature_unit=celsius&wind_speed_unit=kmh"
    )
    with urlopen(url, timeout=5) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw)


@router.get("/api/weather/current")
def api_weather_current(request: Request, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    err = require_auth(request, x_api_key)
    if err:
        return err

    lat = state._gps_latest.get("lat")
    lon = state._gps_latest.get("lon")
    if lat is None or lon is None:
        state._weather_latest.update({
            "ok": False,
            "error": "no_gps_fix",
        })
        return JSONResponse(state._weather_latest)

    now = int(time.time())
    cached_ts = state._weather_latest.get("ts") or 0
    cached_lat = state._weather_latest.get("lat")
    cached_lon = state._weather_latest.get("lon")

    # Cache for 60s if coords unchanged (rounded to 3 decimals ~110m)
    if (
        cached_ts
        and (now - int(cached_ts)) < 60
        and cached_lat is not None
        and cached_lon is not None
        and round(cached_lat, 3) == round(lat, 3)
        and round(cached_lon, 3) == round(lon, 3)
    ):
        return JSONResponse(state._weather_latest)

    try:
        data = _fetch_open_meteo(lat, lon)
        current = data.get("current") or {}
        temp_c = current.get("temperature_2m")
        wind_kmh = current.get("wind_speed_10m")
        weather_code = current.get("weather_code")

        state._weather_latest.update({
            "ts": now,
            "lat": lat,
            "lon": lon,
            "temp_c": temp_c,
            "wind_kmh": wind_kmh,
            "weather_code": weather_code,
            "ok": True,
            "error": None,
        })
        db_insert_weather_sample(now, temp_c)
    except URLError as e:
        state._weather_latest.update({
            "ok": False,
            "error": f"fetch_error: {e}",
        })
    except Exception as e:
        state._weather_latest.update({
            "ok": False,
            "error": f"fetch_error: {e}",
        })

    return JSONResponse(state._weather_latest)


@router.get("/api/weather/history")
def api_weather_history(
    request: Request,
    range: Optional[str] = None,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    err = require_auth(request, x_api_key)
    if err:
        return err

    now = int(time.time())
    if range == "week":
        since = now - 7 * 24 * 3600
    elif range == "month":
        since = now - 30 * 24 * 3600
    elif range == "year":
        since = now - 365 * 24 * 3600
    else:
        since = now - 24 * 3600

    rows = db_query_weather_since(since, limit=20000)
    return JSONResponse({"since": since, "now": now, "rows": rows})
