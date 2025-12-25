import os
import time
import sqlite3
import threading
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, Request, Form, Header, Body
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

# =========================
# Config (no hardcoded IPs)
# =========================

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = Path(os.environ.get("SMARTIFY_STATIC_DIR", str(BASE_DIR / "static")))
# normalize & resolve path (works with absolute or relative)
STATIC_DIR = STATIC_DIR.expanduser().resolve()
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "smartify.db"

SMARTIFY_REQUIRE_AUTH = os.environ.get("SMARTIFY_REQUIRE_AUTH", "1").lower() not in ("0", "false", "no")
SMARTIFY_API_KEY = os.environ.get("SMARTIFY_API_KEY", "").strip()

SMARTIFY_USERNAME = os.environ.get("SMARTIFY_USERNAME", "adinpinjo")
SMARTIFY_PASSWORD = os.environ.get("SMARTIFY_PASSWORD", "changeme")

SMARTIFY_SESSION_SECRET = os.environ.get("SMARTIFY_SESSION_SECRET", "").strip() or "change-me-in-env"

GPS_DEVICE = os.environ.get("SMARTIFY_GPS_DEVICE", "/dev/ttyACM0").strip()
GPS_BAUD = int(os.environ.get("SMARTIFY_GPS_BAUD", "9600"))

DHT22_PINS_RAW = os.environ.get("SMARTIFY_DHT22_PINS", "4").strip()
DHT22_PINS: List[int] = []
for part in [p.strip() for p in DHT22_PINS_RAW.split(",") if p.strip()]:
    try:
        DHT22_PINS.append(int(part))
    except ValueError:
        pass
if not DHT22_PINS:
    DHT22_PINS = [4]

SENSOR_LOG_INTERVAL = int(os.environ.get("SMARTIFY_SENSOR_LOG_INTERVAL", "30"))
SMARTIFY_TRUST_LOCALHOST = os.environ.get("SMARTIFY_TRUST_LOCALHOST", "0").lower() in ("1", "true", "yes")


# =========================
# App + Middleware
# =========================

app = FastAPI(title="Smartify Dashboard API")

# CORS middleware - allow all origins for local network access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for local network
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(
    SessionMiddleware,
    secret_key=SMARTIFY_SESSION_SECRET,
    same_site="lax",
    https_only=False,
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# =========================
# DB helpers
# =========================

def db_init() -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS temperature_readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            sensor_index INTEGER NOT NULL,
            temperature_c REAL,
            humidity REAL
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS gps_fixes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            lat REAL,
            lon REAL,
            speed_kmh REAL,
            course REAL,
            altitude_m REAL
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS relay_states (
            name TEXT PRIMARY KEY,
            pin INTEGER NOT NULL,
            state TEXT NOT NULL,
            updated_at INTEGER NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()


def db_insert_temp(ts: int, sensor_index: int, t: Optional[float], h: Optional[float]) -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO temperature_readings (ts, sensor_index, temperature_c, humidity) VALUES (?, ?, ?, ?)",
        (ts, sensor_index, t, h),
    )
    conn.commit()
    conn.close()


def db_insert_gps(ts: int, lat: Optional[float], lon: Optional[float], speed_kmh: Optional[float],
                  course: Optional[float], altitude_m: Optional[float]) -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO gps_fixes (ts, lat, lon, speed_kmh, course, altitude_m) VALUES (?, ?, ?, ?, ?, ?)",
        (ts, lat, lon, speed_kmh, course, altitude_m),
    )
    conn.commit()
    conn.close()


def db_query_temp_since(since_ts: int, sensor_index: Optional[int] = None) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    if sensor_index is None:
        cur.execute(
            "SELECT ts, sensor_index, temperature_c, humidity FROM temperature_readings WHERE ts >= ? ORDER BY ts ASC",
            (since_ts,),
        )
    else:
        cur.execute(
            "SELECT ts, sensor_index, temperature_c, humidity FROM temperature_readings WHERE ts >= ? AND sensor_index = ? ORDER BY ts ASC",
            (since_ts, sensor_index),
        )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def db_query_gps_since(since_ts: int, limit: int = 1000) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        "SELECT ts, lat, lon, speed_kmh, course, altitude_m FROM gps_fixes WHERE ts >= ? ORDER BY ts ASC LIMIT ?",
        (since_ts, limit),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def db_get_relay_state(name: str) -> Optional[Dict[str, Any]]:
    """Get relay state from database. Returns None if not found."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT name, pin, state, updated_at FROM relay_states WHERE name = ?", (name,))
    row = cur.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


def db_set_relay_state(name: str, pin: int, state: str) -> None:
    """Set relay state in database. state must be 'on' or 'off'."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    now = int(time.time())
    cur.execute(
        "INSERT OR REPLACE INTO relay_states (name, pin, state, updated_at) VALUES (?, ?, ?, ?)",
        (name, pin, state, now),
    )
    conn.commit()
    conn.close()


# =========================
# Auth helpers
# =========================

def is_localhost(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in ("127.0.0.1", "::1", "localhost")


def is_authenticated(request: Request, x_api_key: Optional[str]) -> bool:
    if not SMARTIFY_REQUIRE_AUTH:
        return True

    if SMARTIFY_TRUST_LOCALHOST and is_localhost(request):
        return True

    if request.session.get("logged_in") is True:
        return True

    if SMARTIFY_API_KEY and x_api_key and x_api_key.strip() == SMARTIFY_API_KEY:
        return True

    return False


def require_auth(request: Request, x_api_key: Optional[str]) -> Optional[JSONResponse]:
    if is_authenticated(request, x_api_key):
        return None
    return JSONResponse({"error": "unauthorized"}, status_code=401)


# =========================
# Sensor: DHT22
# =========================

_dht_lock = threading.Lock()
_temp_latest: Dict[str, Any] = {
    "ts": None,
    "sensors": [],
}

def read_dht22_all() -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    try:
        import adafruit_dht
        import board
    except Exception as e:
        for idx, pin in enumerate(DHT22_PINS):
            results.append({
                "sensor_index": idx,
                "pin": pin,
                "temperature_c": None,
                "humidity": None,
                "ok": False,
                "error": f"DHT libs not installed: {e}"
            })
        return results

    board_attr_map = {i: f"D{i}" for i in range(0, 28)}
    now = int(time.time())

    with _dht_lock:
        for idx, pin in enumerate(DHT22_PINS):
            t = None
            h = None
            ok = False
            err = None

            try:
                attr = board_attr_map.get(pin)
                if not attr or not hasattr(board, attr):
                    raise RuntimeError(f"Unsupported pin mapping for BCM {pin} (board.{attr} not found)")

                gpio_obj = getattr(board, attr)
                sensor = adafruit_dht.DHT22(gpio_obj, use_pulseio=False)

                try:
                    t = float(sensor.temperature) if sensor.temperature is not None else None
                    h = float(sensor.humidity) if sensor.humidity is not None else None
                    ok = (t is not None and h is not None)
                finally:
                    try:
                        sensor.exit()
                    except Exception:
                        pass

            except Exception as e:
                err = str(e)

            results.append({
                "sensor_index": idx,
                "pin": pin,
                "temperature_c": t,
                "humidity": h,
                "ok": ok,
                "error": err
            })

            db_insert_temp(now, idx, t, h)

    return results


def _dht22_poller_thread() -> None:
    """Background thread that polls DHT22 sensors at fixed intervals."""
    global _temp_latest
    
    while True:
        try:
            results = read_dht22_all()
            _temp_latest.update({
                "ts": int(time.time()),
                "sensors": results,
            })
        except Exception as e:
            _temp_latest.update({
                "ts": int(time.time()),
                "sensors": [],
                "error": str(e),
            })
        
        # Poll every SENSOR_LOG_INTERVAL seconds (default 30s)
        time.sleep(SENSOR_LOG_INTERVAL)


# =========================
# Sensor: GPS (USB NMEA)
# =========================

_gps_latest: Dict[str, Any] = {
    "ts": None,
    "lat": None,
    "lon": None,
    "speed_kmh": None,
    "course": None,
    "altitude_m": None,
    "satellites": None,
    "source": "nmea",
    "device": GPS_DEVICE,
    "ok": False,
    "error": None,
}


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
        
        # Determine degrees length based on hemisphere:
        # N/S (latitude) = 2 digits, E/W (longitude) = 3 digits
        hemi_upper = hemi.upper()
        if hemi_upper in ("N", "S"):
            deg_len = 2  # Latitude: ddmm.mmmm
        elif hemi_upper in ("E", "W"):
            deg_len = 3  # Longitude: dddmm.mmmm
        else:
            return None  # Invalid hemisphere
        
        deg = float(coord[:deg_len])
        minutes = float(coord[deg_len:])
        dec = deg + minutes / 60.0
        
        # Apply sign based on hemisphere
        if hemi_upper in ("S", "W"):
            dec *= -1.0
        
        return dec
    except Exception:
        return None


def _gps_reader_thread() -> None:
    global _gps_latest
    try:
        import serial
    except Exception as e:
        _gps_latest["ok"] = False
        _gps_latest["error"] = f"pyserial not available: {e}"
        return

    while True:
        try:
            if not Path(GPS_DEVICE).exists():
                _gps_latest["ok"] = False
                _gps_latest["error"] = f"GPS device not found: {GPS_DEVICE}"
                time.sleep(2)
                continue

            # Use timeout for serial reads to prevent blocking
            with serial.Serial(GPS_DEVICE, GPS_BAUD, timeout=2) as ser:
                _gps_latest["error"] = None
                while True:
                    try:
                        # readline with timeout will return empty string if timeout
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

                            _gps_latest.update({
                                "ts": now,
                                "lat": lat,
                                "lon": lon,
                                "speed_kmh": speed_kmh,
                                "course": course,
                                "ok": True,
                                "error": None,
                            })
                            db_insert_gps(now, lat, lon, speed_kmh, course, _gps_latest.get("altitude_m"))

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

                            # Extract satellite count (field 7 in GGA sentence)
                            satellites = None
                            try:
                                if len(parts) > 7 and parts[7]:
                                    satellites = int(parts[7])
                            except Exception:
                                satellites = None

                            _gps_latest.update({
                                "ts": now,
                                "lat": lat if lat is not None else _gps_latest.get("lat"),
                                "lon": lon if lon is not None else _gps_latest.get("lon"),
                                "altitude_m": alt,
                                "satellites": satellites,
                                "ok": True,
                                "error": None,
                            })
                            db_insert_gps(now, _gps_latest.get("lat"), _gps_latest.get("lon"),
                                          _gps_latest.get("speed_kmh"), _gps_latest.get("course"), alt)

                    except serial.SerialTimeoutException:
                        # Timeout is normal, continue polling
                        continue
                    except Exception as e:
                        _gps_latest["ok"] = False
                        _gps_latest["error"] = f"Serial read error: {e}"
                        time.sleep(1)
                        continue

        except Exception as e:
            _gps_latest["ok"] = False
            _gps_latest["error"] = f"GPS read error: {e}"
            time.sleep(2)


# =========================
# Startup
# =========================

@app.on_event("startup")
def on_startup() -> None:
    db_init()
    # Initialize relay states
    _init_relay_state(HEADER_RELAY_NAME, HEADER_RELAY_PIN)
    # Start GPS reader thread
    t_gps = threading.Thread(target=_gps_reader_thread, daemon=True)
    t_gps.start()
    # Start DHT22 poller thread
    t_dht = threading.Thread(target=_dht22_poller_thread, daemon=True)
    t_dht.start()


# =========================
# Auth routes
# =========================

@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == SMARTIFY_USERNAME and password == SMARTIFY_PASSWORD:
        request.session["logged_in"] = True
        request.session["user"] = username
        return JSONResponse({"ok": True})
    return JSONResponse({"ok": False, "error": "invalid_credentials"}, status_code=401)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return JSONResponse({"ok": True})


@app.get("/api/me")
def api_me(request: Request, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    authed = is_authenticated(request, x_api_key)
    return JSONResponse({
        "authenticated": authed,
        "user": request.session.get("user") if authed else None,
        "require_auth": SMARTIFY_REQUIRE_AUTH,
        "api_key_enabled": bool(SMARTIFY_API_KEY),
        "trusted_localhost": SMARTIFY_TRUST_LOCALHOST,
    })


# =========================
# API: Temperature
# =========================

@app.get("/api/temperature/latest")
def api_temperature_latest(request: Request, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    err = require_auth(request, x_api_key)
    if err:
        return err
    # Return cached values immediately (no blocking sensor reads)
    return JSONResponse(_temp_latest)


@app.get("/api/temperature/history")
def api_temperature_history(
    request: Request,
    range: str = "day",
    sensor: Optional[int] = None,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    err = require_auth(request, x_api_key)
    if err:
        return err

    now = int(time.time())
    # Determine time window
    if range == "hour":
        since = now - 3600
        bucket_seconds = 300  # 5 minutes
    elif range == "day":
        since = now - 86400
        bucket_seconds = 300  # 5 minutes
    elif range == "week":
        since = now - 7 * 86400
        bucket_seconds = 1800  # 30 minutes
    elif range == "month":
        since = now - 30 * 86400
        bucket_seconds = 7200  # 2 hours
    elif range == "year":
        since = now - 365 * 86400
        bucket_seconds = 86400  # 1 day
    else:
        return JSONResponse({"error": "invalid_range", "allowed": ["hour", "day", "week", "month", "year"]}, status_code=400)

    # Get all raw rows
    raw_rows = db_query_temp_since(since, sensor_index=sensor)
    
    # Bucket/aggregate data by time window
    buckets: Dict[int, Dict[int, List[float]]] = {}  # bucket_ts -> sensor_index -> [temps]
    
    for row in raw_rows:
        ts = row["ts"]
        sensor_idx = row["sensor_index"]
        temp = row["temperature_c"]
        
        if temp is None:
            continue
        
        # Calculate bucket timestamp (round down to bucket boundary)
        bucket_ts = (ts // bucket_seconds) * bucket_seconds
        
        if bucket_ts not in buckets:
            buckets[bucket_ts] = {}
        if sensor_idx not in buckets[bucket_ts]:
            buckets[bucket_ts][sensor_idx] = []
        
        buckets[bucket_ts][sensor_idx].append(temp)
    
    # Convert buckets to rows (average temperatures per bucket)
    # Group by bucket_ts and include both sensors
    aggregated_rows = []
    for bucket_ts in sorted(buckets.keys()):
        sensor_data = buckets[bucket_ts]
        # Ensure we have entries for both sensors (0 and 1) if they exist
        for sensor_idx in [0, 1]:
            if sensor_idx in sensor_data:
                temps = sensor_data[sensor_idx]
                avg_temp = sum(temps) / len(temps) if temps else None
                aggregated_rows.append({
                    "ts": bucket_ts,
                    "sensor_index": sensor_idx,
                    "temperature_c": avg_temp,
                    "humidity": None,  # We're only aggregating temperature for now
                })
    
    return JSONResponse({
        "since": since,
        "now": now,
        "rows": aggregated_rows,
        "bucket_seconds": bucket_seconds,
    })


# =========================
# API: GPS
# =========================

@app.get("/api/gps/current")
def api_gps_current(request: Request, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    err = require_auth(request, x_api_key)
    if err:
        return err
    return JSONResponse(_gps_latest)


@app.get("/api/gps/track")
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


# =========================
# Relay Control
# =========================

_relay_lock = threading.Lock()
RELAY_SCRIPT = "/usr/local/bin/relay27.py"
HEADER_RELAY_NAME = "header"
HEADER_RELAY_PIN = 27


def _set_relay_state(name: str, pin: int, state: str, save_to_db: bool = True) -> Dict[str, Any]:
    """
    Set relay state by executing sudo command.
    state must be 'on' or 'off'.
    save_to_db: if True, also persist state to database (default True).
    Returns dict with success status.
    """
    if state not in ("on", "off"):
        return {"ok": False, "error": "invalid_state", "message": "state must be 'on' or 'off'"}

    try:
        cmd = ["sudo", RELAY_SCRIPT, state]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        
        if proc.returncode != 0:
            return {
                "ok": False,
                "error": "relay_command_failed",
                "message": proc.stderr.strip() or f"Command failed with code {proc.returncode}",
            }
        
        # Store state in database if requested
        if save_to_db:
            db_set_relay_state(name, pin, state)
        
        return {"ok": True, "state": state}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout", "message": "Relay command timed out"}
    except Exception as e:
        return {"ok": False, "error": "exception", "message": str(e)}


def _init_relay_state(name: str, pin: int) -> None:
    """
    Initialize relay state on startup.
    Reads state from DB (defaults to 'off' if not found) and sets the relay.
    Does NOT save to DB (already in DB).
    """
    stored = db_get_relay_state(name)
    state = stored["state"] if stored else "off"
    
    # Set the actual relay to the stored state (don't save to DB, it's already there)
    result = _set_relay_state(name, pin, state, save_to_db=False)
    if not result.get("ok"):
        # Log error but don't crash on startup
        print(f"[Relay] Warning: Failed to initialize {name} relay to {state}: {result.get('message')}")


# =========================
# API: Network (nmcli)
# =========================

def run_nmcli(args: List[str]) -> subprocess.CompletedProcess:
    cmd = ["nmcli"] + args
    return subprocess.run(cmd, capture_output=True, text=True)


@app.get("/api/network/status")
def api_network_status(request: Request, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    err = require_auth(request, x_api_key)
    if err:
        return err

    proc = run_nmcli(["-t", "-f", "ACTIVE,SSID,DEVICE", "dev", "wifi"])
    if proc.returncode != 0:
        return JSONResponse({"error": "nmcli_failed", "stderr": proc.stderr.strip()}, status_code=500)

    lines = [l.strip() for l in proc.stdout.splitlines() if l.strip()]
    return JSONResponse({"rows": lines})


@app.get("/api/network/scan")
def api_network_scan(request: Request, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    err = require_auth(request, x_api_key)
    if err:
        return err

    proc = run_nmcli(["-t", "-f", "SSID,SIGNAL,SECURITY", "dev", "wifi", "list"])
    if proc.returncode != 0:
        return JSONResponse({"error": "nmcli_failed", "stderr": proc.stderr.strip()}, status_code=500)

    rows = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split(":")
        ssid = parts[0] if len(parts) > 0 else ""
        signal = parts[1] if len(parts) > 1 else ""
        security = parts[2] if len(parts) > 2 else ""
        rows.append({"ssid": ssid, "signal": signal, "security": security})

    return JSONResponse({"networks": rows})


# =========================
# API: Relay Control
# =========================

@app.get("/api/relay/header")
def api_relay_header_get(request: Request, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    err = require_auth(request, x_api_key)
    if err:
        return err
    
    stored = db_get_relay_state(HEADER_RELAY_NAME)
    if stored:
        return JSONResponse({
            "ok": True,
            "name": HEADER_RELAY_NAME,
            "pin": HEADER_RELAY_PIN,
            "state": stored["state"],
        })
    else:
        # Default to 'off' if not in database
        return JSONResponse({
            "ok": True,
            "name": HEADER_RELAY_NAME,
            "pin": HEADER_RELAY_PIN,
            "state": "off",
        })


@app.post("/api/relay/header")
def api_relay_header_post(
    request: Request,
    body: Dict[str, Any] = Body(...),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    err = require_auth(request, x_api_key)
    if err:
        return err
    
    # Extract and validate state from body
    state = body.get("state", "").strip().lower()
    if state not in ("on", "off"):
        return JSONResponse({"ok": False, "error": "invalid_state", "message": "state must be 'on' or 'off'"}, status_code=400)
    
    # Prevent rapid toggles with lock
    if not _relay_lock.acquire(blocking=False):
        return JSONResponse({"ok": False, "error": "busy", "message": "Another relay operation in progress"}, status_code=429)
    
    try:
        result = _set_relay_state(HEADER_RELAY_NAME, HEADER_RELAY_PIN, state)
        if result.get("ok"):
            return JSONResponse({
                "ok": True,
                "name": HEADER_RELAY_NAME,
                "pin": HEADER_RELAY_PIN,
                "state": state,
            })
        else:
            return JSONResponse({
                "ok": False,
                "error": result.get("error", "unknown"),
                "message": result.get("message", "Failed to set relay state"),
            }, status_code=500)
    finally:
        _relay_lock.release()


# =========================
# Frontend routes
# =========================

def frontend_ready() -> bool:
    return (STATIC_DIR / "index.html").exists()


@app.get("/")
def root():
    if not frontend_ready():
        return JSONResponse({"error": "frontend_not_built"}, status_code=500)
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/dashboard")
def dashboard():
    if not frontend_ready():
        return JSONResponse({"error": "frontend_not_built"}, status_code=500)
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/{full_path:path}")
def spa_fallback(full_path: str):
    if not frontend_ready():
        return JSONResponse({"error": "frontend_not_built"}, status_code=500)
    target = STATIC_DIR / full_path
    if target.exists() and target.is_file():
        return FileResponse(target)
    return FileResponse(STATIC_DIR / "index.html")
