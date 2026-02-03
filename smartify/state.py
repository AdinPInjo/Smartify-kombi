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
