import time
import sqlite3
import math
from datetime import datetime, timezone

import gpsd

DB_PATH = "/home/adinpinjo/smartify/smartify.db"

# How often we read GPS (seconds)
READ_EVERY_SEC = 2

# Filtering (anti-jitter when parked)
MIN_SPEED_M_S = 0.2          # 0.2 m/s ≈ 0.72 km/h
MIN_DIST_METERS = 25.0       # ignore drift smaller than this when not moving
HEARTBEAT_SEC = 60           # store at least one point every N seconds even if parked/no fix

def iso_utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def haversine_m(lat1, lon1, lat2, lon2):
    # Great-circle distance between 2 points on Earth
    R = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def get_last_point(cur):
    cur.execute(
        "SELECT lat, lon, ts FROM track_points WHERE lat IS NOT NULL AND lon IS NOT NULL ORDER BY id DESC LIMIT 1"
    )
    row = cur.fetchone()
    if not row:
        return None
    return {"lat": row[0], "lon": row[1], "ts": row[2]}

def main():
    gpsd.connect()

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    last_saved = get_last_point(cur)
    last_save_time = time.time()

    while True:
        now_ts = iso_utc_now()
        now_time = time.time()

        try:
            packet = gpsd.get_current()
            mode = getattr(packet, "mode", 0)

            lat = lon = speed = None

            if mode >= 2:
                lat, lon = packet.position()
                speed = packet.speed()  # m/s

            should_save = False

            # Always save at least every HEARTBEAT_SEC (even if no fix) so you know it's alive
            if (now_time - last_save_time) >= HEARTBEAT_SEC:
                should_save = True

            # If we have a fix and coordinates:
            if (mode >= 2) and (lat is not None) and (lon is not None):
                # If moving, save
                if (speed is not None) and (speed >= MIN_SPEED_M_S):
                    should_save = True
                else:
                    # Not moving (or speed unreliable): only save if it moved a meaningful distance
                    if last_saved is None:
                        should_save = True
                    else:
                        dist = haversine_m(last_saved["lat"], last_saved["lon"], lat, lon)
                        if dist >= MIN_DIST_METERS:
                            should_save = True

            if should_save:
                cur.execute(
                    "INSERT INTO track_points (ts, lat, lon, speed_m_s, mode) VALUES (?, ?, ?, ?, ?)",
                    (now_ts, lat, lon, speed, mode),
                )
                con.commit()
                last_save_time = now_time
                if (mode >= 2) and (lat is not None) and (lon is not None):
                    last_saved = {"lat": lat, "lon": lon, "ts": now_ts}

        except Exception:
            # GPS can disconnect/reconnect; don't crash
            time.sleep(2)

        time.sleep(READ_EVERY_SEC)

if __name__ == "__main__":
    main()
