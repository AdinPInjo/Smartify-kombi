"""
Sensor reading API endpoints (DHT22, temperature snapshots, history).
"""
import time
from typing import Optional, Dict, List, Any

from fastapi import APIRouter, Request, Header
from fastapi.responses import JSONResponse

# Import from dedicated modules (no circular imports)
from smartify.auth import require_auth
from smartify.db import db_query_temp_since
from smartify.services.sensors import get_sensor_snapshot
from smartify import state


router = APIRouter(tags=["sensors"])


@router.get("/api/temperature/latest")
def api_temperature_latest(request: Request, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    """Return RAW latest sensor readings (for UI/graphs). Old behavior preserved."""
    err = require_auth(request, x_api_key)
    if err:
        return err
    # Return cached raw values immediately (no blocking sensor reads)
    return JSONResponse(state._temp_latest)


@router.get("/api/temperature/snapshot/latest")
def api_temperature_snapshot_latest(request: Request, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    """Return snapshot data (1-minute averages) for relay/rule engine use."""
    err = require_auth(request, x_api_key)
    if err:
        return err
    
    # Import db_get_sensor_snapshot lazily to pass to get_sensor_snapshot
    from smartify.db import db_get_sensor_snapshot
    
    # Return snapshot data for each sensor
    kombi_snapshot = get_sensor_snapshot("kombi", db_get_sensor_snapshot)
    garaza_snapshot = get_sensor_snapshot("garaza", db_get_sensor_snapshot)
    
    # Build response with snapshot data
    sensors = []
    for idx, sensor_name in enumerate(["kombi", "garaza"]):
        snapshot = kombi_snapshot if sensor_name == "kombi" else garaza_snapshot
        sensors.append({
            "sensor_index": idx,
            "sensor_name": sensor_name,
            "avg_temp": snapshot.get("avg_temp"),
            "avg_humidity": snapshot.get("avg_humidity"),
            "sample_count": snapshot.get("sample_count"),
            "updated_at": snapshot.get("updated_at"),
            "last_good_at": snapshot.get("last_good_at"),
            "age_seconds": snapshot.get("age_seconds"),
            "is_stale": snapshot.get("is_stale"),
            "is_ready": snapshot.get("is_ready"),
        })
    
    return JSONResponse({
        "ts": int(time.time()),
        "sensors": sensors,
    })


@router.get("/api/temperature/history")
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
