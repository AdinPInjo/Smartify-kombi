"""
Configuration constants for Smartify.
"""
import os
from pathlib import Path

# Base paths
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "smartify.db"

# Auth configuration
SMARTIFY_REQUIRE_AUTH = os.environ.get("SMARTIFY_REQUIRE_AUTH", "1").lower() not in ("0", "false", "no")
SMARTIFY_API_KEY = os.environ.get("SMARTIFY_API_KEY", "").strip()
SMARTIFY_TRUST_LOCALHOST = os.environ.get("SMARTIFY_TRUST_LOCALHOST", "0").lower() in ("1", "true", "yes")
SMARTIFY_USERNAME = os.environ.get("SMARTIFY_USERNAME", "adinpinjo")
SMARTIFY_PASSWORD = os.environ.get("SMARTIFY_PASSWORD", "changeme")
SMARTIFY_SESSION_SECRET = os.environ.get("SMARTIFY_SESSION_SECRET", "").strip() or "change-me-in-env"

# Sensor configuration
SENSOR_WARMUP_SAMPLES = 6  # Need at least 6 samples (30s) before snapshot is "ready"
SENSOR_STALE_THRESHOLD = 600  # 10 minutes without valid samples = stale
SENSOR_LOG_INTERVAL = int(os.environ.get("SMARTIFY_SENSOR_LOG_INTERVAL", "30"))

# GPS configuration
GPS_DEVICE = os.environ.get("SMARTIFY_GPS_DEVICE", "/dev/ttyACM0").strip()
GPS_BAUD = int(os.environ.get("SMARTIFY_GPS_BAUD", "9600"))

