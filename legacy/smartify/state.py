"""
Shared runtime state for Smartify.

Keep this module lightweight to avoid circular imports.
"""
from typing import Dict, Any

_temp_latest: Dict[str, Any] = {
    "ts": None,
    "sensors": [],
}

_gps_latest: Dict[str, Any] = {
    "ts": None,
    "lat": None,
    "lon": None,
    "speed_kmh": None,
    "course": None,
    "altitude_m": None,
    "satellites": None,
    "source": "nmea",
    "device": None,
    "ok": False,
    "error": None,
}

_weather_latest: Dict[str, Any] = {
    "ts": None,
    "lat": None,
    "lon": None,
    "temp_c": None,
    "wind_kmh": None,
    "weather_code": None,
    "source": "open-meteo",
    "ok": False,
    "error": None,
}

_thread_health: Dict[str, Dict[str, Any]] = {}

# Remote sync status (Supabase desired_state polling)
_remote_sync_status: Dict[str, Any] = {
    "last_poll_ts": None,
    "last_success_ts": None,
    "last_error": None,
    "last_desired_version": None,
    "last_applied_version": None,
    "last_change_count": 0,
}
