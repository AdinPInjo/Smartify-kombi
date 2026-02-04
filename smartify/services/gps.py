"""
GPS reader service (USB NMEA).
Keeps shared state updated in smartify.state without importing smartify.app.
"""
from collections import deque
from pathlib import Path
import threading
import time
from typing import Optional

from smartify import state
from smartify.config import GPS_DEVICE, GPS_BAUD
from smartify.db import db_insert_gps


def _nmea_to_decimal(coord: str, hemi: str) -> Optional[float]:
    """
    Convert NMEA coordinate format (ddmm.mmmm or dddmm.mmmm) to decimal degrees.

    - Latitude (N/S): uses 2 digits for degrees (ddmm.mmmm)
    - Longitude (E/W): uses 3 digits for degrees (dddmm.mmmm)
    """
    if not coord or not hemi:
        return None
    try:
        if "." not in coord:
            return None

        hemi_upper = hemi.upper()
        if hemi_upper in ("N", "S"):
            deg_len = 2
        elif hemi_upper in ("E", "W"):
            deg_len = 3
        else:
            return None

        deg = float(coord[:deg_len])
        minutes = float(coord[deg_len:])
        dec = deg + minutes / 60.0

        if hemi_upper in ("S", "W"):
            dec *= -1.0

        return dec
    except Exception:
        return None


def _gps_reader_thread() -> None:
    try:
        import serial
    except Exception as e:
        state._gps_latest["ok"] = False
        state._gps_latest["error"] = f"pyserial not available: {e}"
        return

    # Stationary smoothing (reduce jitter when not moving)
    stationary_speed_kmh = 1.0
    stationary_emit_interval = 5
    stationary_window_seconds = 5
    last_stationary_emit = 0
    sample_buffer = deque(maxlen=200)

    while True:
        try:
            if not Path(GPS_DEVICE).exists():
                state._gps_latest["ok"] = False
                state._gps_latest["error"] = f"GPS device not found: {GPS_DEVICE}"
                time.sleep(2)
                continue

            with serial.Serial(GPS_DEVICE, GPS_BAUD, timeout=2) as ser:
                state._gps_latest["error"] = None

                latest_lat = state._gps_latest.get("lat")
                latest_lon = state._gps_latest.get("lon")
                latest_speed = state._gps_latest.get("speed_kmh")
                latest_course = state._gps_latest.get("course")
                latest_alt = state._gps_latest.get("altitude_m")
                latest_sats = state._gps_latest.get("satellites")

                def _record_sample(ts: int, lat: Optional[float], lon: Optional[float], speed: Optional[float]) -> None:
                    if lat is None or lon is None:
                        return
                    sample_buffer.append({
                        "ts": ts,
                        "lat": lat,
                        "lon": lon,
                        "speed": speed,
                    })

                def _emit_update(ts: int, lat: Optional[float], lon: Optional[float], speed: Optional[float],
                                 course: Optional[float], alt: Optional[float], sats: Optional[int]) -> None:
                    state._gps_latest.update({
                        "ts": ts,
                        "lat": lat,
                        "lon": lon,
                        "speed_kmh": speed,
                        "course": course,
                        "altitude_m": alt,
                        "satellites": sats,
                        "ok": True,
                        "error": None,
                    })
                    db_insert_gps(ts, lat, lon, speed, course, alt)

                while True:
                    try:
                        line = ser.readline().decode(errors="ignore").strip()
                        if not line or not line.startswith("$"):
                            continue

                        parts = line.split(",")
                        if not parts:
                            continue
                        sentence = parts[0]
                        now = int(time.time())

                        if sentence.endswith("RMC") and len(parts) >= 12:
                            status = parts[2] if len(parts) > 2 else ""
                            if status != "A":
                                continue

                            lat = _nmea_to_decimal(parts[3], parts[4])
                            lon = _nmea_to_decimal(parts[5], parts[6])

                            speed_kn = None
                            course = None
                            try:
                                speed_kn = float(parts[7]) if parts[7] else None
                            except Exception:
                                speed_kn = None
                            try:
                                course = float(parts[8]) if parts[8] else None
                            except Exception:
                                course = None

                            speed_kmh = speed_kn * 1.852 if speed_kn is not None else None

                            latest_lat = lat if lat is not None else latest_lat
                            latest_lon = lon if lon is not None else latest_lon
                            latest_speed = speed_kmh if speed_kmh is not None else latest_speed
                            latest_course = course if course is not None else latest_course

                            _record_sample(now, latest_lat, latest_lon, latest_speed)

                            if latest_speed is not None and latest_speed < stationary_speed_kmh:
                                if (now - last_stationary_emit) >= stationary_emit_interval:
                                    cutoff = now - stationary_window_seconds
                                    samples = [s for s in sample_buffer if s["ts"] >= cutoff]
                                    if samples:
                                        avg_lat = sum(s["lat"] for s in samples) / len(samples)
                                        avg_lon = sum(s["lon"] for s in samples) / len(samples)
                                        avg_speed = None
                                        speed_samples = [s["speed"] for s in samples if s["speed"] is not None]
                                        if speed_samples:
                                            avg_speed = sum(speed_samples) / len(speed_samples)
                                        _emit_update(now, avg_lat, avg_lon, avg_speed, latest_course, latest_alt, latest_sats)
                                        last_stationary_emit = now
                            else:
                                _emit_update(now, latest_lat, latest_lon, latest_speed, latest_course, latest_alt, latest_sats)

                        if sentence.endswith("GGA") and len(parts) >= 10:
                            fix = parts[6] if len(parts) > 6 else "0"
                            if fix == "0":
                                continue

                            lat = _nmea_to_decimal(parts[2], parts[3])
                            lon = _nmea_to_decimal(parts[4], parts[5])

                            alt = None
                            try:
                                alt = float(parts[9]) if parts[9] else None
                            except Exception:
                                alt = None

                            satellites = None
                            try:
                                if len(parts) > 7 and parts[7]:
                                    satellites = int(parts[7])
                            except Exception:
                                satellites = None

                            latest_lat = lat if lat is not None else latest_lat
                            latest_lon = lon if lon is not None else latest_lon
                            latest_alt = alt if alt is not None else latest_alt
                            latest_sats = satellites if satellites is not None else latest_sats

                            _record_sample(now, latest_lat, latest_lon, latest_speed)

                            if latest_speed is not None and latest_speed < stationary_speed_kmh:
                                if (now - last_stationary_emit) >= stationary_emit_interval:
                                    cutoff = now - stationary_window_seconds
                                    samples = [s for s in sample_buffer if s["ts"] >= cutoff]
                                    if samples:
                                        avg_lat = sum(s["lat"] for s in samples) / len(samples)
                                        avg_lon = sum(s["lon"] for s in samples) / len(samples)
                                        avg_speed = None
                                        speed_samples = [s["speed"] for s in samples if s["speed"] is not None]
                                        if speed_samples:
                                            avg_speed = sum(speed_samples) / len(speed_samples)
                                        _emit_update(now, avg_lat, avg_lon, avg_speed, latest_course, latest_alt, latest_sats)
                                        last_stationary_emit = now
                            else:
                                _emit_update(now, latest_lat, latest_lon, latest_speed, latest_course, latest_alt, latest_sats)

                    except serial.SerialTimeoutException:
                        continue
                    except Exception as e:
                        state._gps_latest["ok"] = False
                        state._gps_latest["error"] = f"Serial read error: {e}"
                        time.sleep(1)
                        continue

        except Exception as e:
            state._gps_latest["ok"] = False
            state._gps_latest["error"] = f"GPS read error: {e}"
            time.sleep(2)


def start_gps_thread() -> None:
    state._gps_latest["device"] = GPS_DEVICE
    t_gps = threading.Thread(target=_gps_reader_thread, daemon=True)
    t_gps.start()
