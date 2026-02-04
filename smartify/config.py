"""
Centralized configuration for Smartify.
All environment variables and constants are defined here.
"""
import os
import threading
from pathlib import Path
from typing import Optional

# Import logger for config logging
from smartify.logging_setup import logger

# =========================
# Configuration / Settings
# =========================
# All module-level constants defined here to prevent NameError on import.
# Override via environment variables as needed.

# Paths
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = REPO_ROOT / "smartify" / "data" / "smartify.db"
DB_PATH = os.getenv("SMARTIFY_DB_PATH", str(DEFAULT_DB_PATH))
DATA_DIR = REPO_ROOT / "smartify" / "data"
STATIC_DIR = REPO_ROOT / "smartify-ui" / "dist"

# Authentication & Security
SMARTIFY_USERNAME = os.getenv("SMARTIFY_USERNAME", "admin")
SMARTIFY_PASSWORD = os.getenv("SMARTIFY_PASSWORD", "changeme")
SMARTIFY_API_KEY = os.getenv("SMARTIFY_API_KEY", "")
SMARTIFY_REQUIRE_AUTH = os.getenv("SMARTIFY_REQUIRE_AUTH", "1") in ("1", "true", "yes", "on")
SMARTIFY_TRUST_LOCALHOST = os.getenv("SMARTIFY_TRUST_LOCALHOST", "1") in ("1", "true", "yes", "on")
SMARTIFY_SECRET = os.getenv("SMARTIFY_SECRET", "change-this-secret-in-production")

# Remote sync (Supabase)
SMARTIFY_SUPABASE_URL = os.getenv("SMARTIFY_SUPABASE_URL", "").strip()
SMARTIFY_SUPABASE_SERVICE_KEY = (
    os.getenv("SMARTIFY_SUPABASE_SERVICE_KEY", "").strip()
    or os.getenv("SMARTIFY_SUPABASE_SERVICE_ROLE_KEY", "").strip()
)
SMARTIFY_DEVICE_ID = os.getenv("SMARTIFY_DEVICE_ID", "").strip()
SMARTIFY_REMOTE_SYNC_ENABLED = os.getenv("SMARTIFY_REMOTE_SYNC_ENABLED", "0") in ("1", "true", "yes", "on")
SMARTIFY_REMOTE_SYNC_INTERVAL_SECONDS = int(os.getenv("SMARTIFY_REMOTE_SYNC_INTERVAL_SECONDS", "10"))

# GPS configuration
GPS_ENABLED = os.getenv("GPS_ENABLED", "0") in ("1", "true", "yes", "on")
GPS_DEVICE = os.getenv("GPS_DEVICE", "/dev/serial0")
GPS_BAUD = int(os.getenv("GPS_BAUD", "9600"))

# DHT22 temperature/humidity sensor pins
DHT22_PINS_RAW = os.getenv("SMARTIFY_DHT22_PINS")
logger.info("[Config] RAW SMARTIFY_DHT22_PINS=%r", DHT22_PINS_RAW)
if DHT22_PINS_RAW and DHT22_PINS_RAW.strip():
    DHT22_PINS = [int(p.strip()) for p in DHT22_PINS_RAW.split(",") if p.strip().isdigit()]
else:
    DHT22_PINS = []  # No DHT22 sensors configured
logger.info("[Config] DHT22_PINS=%s", DHT22_PINS)

# Sensor polling interval
SENSOR_LOG_INTERVAL = int(os.getenv("SENSOR_LOG_INTERVAL", "30"))
SENSOR_WARMUP_SAMPLES = int(os.getenv("SENSOR_WARMUP_SAMPLES", "6"))
SENSOR_STALE_THRESHOLD = int(os.getenv("SENSOR_STALE_THRESHOLD", "600"))

# Legacy header relay (single relay control)
HEADER_RELAY_NAME = os.getenv("HEADER_RELAY_NAME", "header")
HEADER_RELAY_PIN = int(os.getenv("HEADER_RELAY_PIN", "0"))

# Thread-safety lock for relay operations
_relay_lock = threading.Lock()

# Rule evaluator thread handle (set during startup)
_rule_evaluator_thread: Optional[threading.Thread] = None

# Startup log
print(f"[Config] DB_PATH={DB_PATH}")
print(f"[Config] GPS_ENABLED={GPS_ENABLED}, GPS_DEVICE={GPS_DEVICE if GPS_ENABLED else 'N/A'}")
print(f"[Config] SMARTIFY_REQUIRE_AUTH={SMARTIFY_REQUIRE_AUTH}")
