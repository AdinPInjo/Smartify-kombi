"""
Background weather fetcher (Open-Meteo, no API key required).
Keeps shared weather state updated and persists samples to DB.
"""
import json
import threading
import time
from typing import Optional
from urllib.request import urlopen
from urllib.error import URLError

from smartify import state
from smartify.db import db_insert_weather_sample


_FETCH_INTERVAL_SECONDS = 20 * 60


def _fetch_open_meteo(lat: float, lon: float) -> dict:
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat:.6f}&longitude={lon:.6f}"
        "&current=temperature_2m,weather_code,wind_speed_10m"
        "&temperature_unit=celsius&wind_speed_unit=kmh"
    )
    with urlopen(url, timeout=8) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw)


def _weather_thread() -> None:
    last_fetch_ts = 0
    last_lat: Optional[float] = None
    last_lon: Optional[float] = None

    while True:
        try:
            lat = state._gps_latest.get("lat")
            lon = state._gps_latest.get("lon")
            if lat is None or lon is None:
                time.sleep(5)
                continue

            now = int(time.time())
            if (now - last_fetch_ts) < _FETCH_INTERVAL_SECONDS:
                time.sleep(5)
                continue

            # Skip if coords are effectively unchanged (rounded to 3 decimals ~110m)
            if last_lat is not None and last_lon is not None:
                if round(last_lat, 3) == round(lat, 3) and round(last_lon, 3) == round(lon, 3):
                    if (now - last_fetch_ts) < _FETCH_INTERVAL_SECONDS:
                        time.sleep(5)
                        continue

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
            last_fetch_ts = now
            last_lat = lat
            last_lon = lon
        except URLError as e:
            state._weather_latest.update({
                "ok": False,
                "error": f"fetch_error: {e}",
            })
            time.sleep(10)
        except Exception as e:
            state._weather_latest.update({
                "ok": False,
                "error": f"fetch_error: {e}",
            })
            time.sleep(10)


def start_weather_thread() -> None:
    t = threading.Thread(target=_weather_thread, daemon=True)
    t.start()
