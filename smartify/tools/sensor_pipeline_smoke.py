#!/usr/bin/env python3
"""
Sensor Pipeline Smoke Test

Tests the sensor sample → snapshot refresh pipeline by:
1. Inserting a fake sample into sensor_samples for 'kombi'
2. Triggering snapshot refresh logic
3. Asserting sensor_snapshot.updated_at changes

Usage:
    cd /home/adinpinjo/repos/Smartify-kombi
    ./smartify/.venv/bin/python -m smartify.tools.sensor_pipeline_smoke
"""

import sys
import time
import sqlite3
from pathlib import Path

# Determine DB path
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = REPO_ROOT / "smartify" / "data" / "smartify.db"

def get_snapshot_updated_at(conn, sensor_name: str):
    """Get current updated_at timestamp for sensor snapshot."""
    cur = conn.cursor()
    cur.execute("SELECT updated_at FROM sensor_snapshot WHERE sensor_name = ?", (sensor_name,))
    row = cur.fetchone()
    return row[0] if row else None

def insert_fake_sample(conn, sensor_name: str, temp: float, humidity: float):
    """Insert a fake sensor sample."""
    cur = conn.cursor()
    now = int(time.time())
    cur.execute(
        "INSERT INTO sensor_samples (sensor_name, temp, humidity, ok, created_at) VALUES (?, ?, ?, ?, ?)",
        (sensor_name, temp, humidity, 1, now)
    )
    conn.commit()
    print(f"✓ Inserted fake sample: sensor={sensor_name} temp={temp} hum={humidity} created_at={now}")
    return now

def refresh_snapshot(conn, sensor_name: str, window_start: int, window_end: int):
    """Compute and update sensor snapshot from recent samples."""
    cur = conn.cursor()
    
    # Get valid samples from window
    cur.execute(
        """SELECT temp, humidity FROM sensor_samples
           WHERE sensor_name = ? AND ok = 1 AND created_at >= ? AND created_at < ?""",
        (sensor_name, window_start, window_end)
    )
    samples = cur.fetchall()
    
    if not samples:
        print(f"✗ No valid samples found for {sensor_name} in window [{window_start}, {window_end})")
        return False
    
    # Compute averages
    avg_temp = sum(s[0] for s in samples if s[0] is not None) / len(samples)
    avg_humidity = sum(s[1] for s in samples if s[1] is not None) / len(samples)
    sample_count = len(samples)
    now = int(time.time())
    
    # Upsert snapshot
    cur.execute(
        """INSERT INTO sensor_snapshot (sensor_name, avg_temp, avg_humidity, sample_count, window_start, window_end, last_good_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(sensor_name) DO UPDATE SET
               avg_temp = excluded.avg_temp,
               avg_humidity = excluded.avg_humidity,
               sample_count = excluded.sample_count,
               window_start = excluded.window_start,
               window_end = excluded.window_end,
               last_good_at = excluded.last_good_at,
               updated_at = excluded.updated_at""",
        (sensor_name, avg_temp, avg_humidity, sample_count, window_start, window_end, now, now)
    )
    conn.commit()
    print(f"✓ Refreshed snapshot: sensor={sensor_name} avg_temp={avg_temp:.1f} avg_hum={avg_humidity:.1f} samples={sample_count}")
    return True

def main():
    print(f"[Sensor Pipeline Smoke Test]")
    print(f"DB_PATH: {DB_PATH}")
    
    if not DB_PATH.exists():
        print(f"✗ Database not found at {DB_PATH}")
        sys.exit(1)
    
    sensor_name = "kombi"
    
    try:
        conn = sqlite3.connect(str(DB_PATH))
        
        # Step 1: Get initial snapshot updated_at
        initial_updated_at = get_snapshot_updated_at(conn, sensor_name)
        print(f"Initial snapshot updated_at: {initial_updated_at}")
        
        # Step 2: Insert fake sample
        sample_ts = insert_fake_sample(conn, sensor_name, temp=21.5, humidity=55.0)
        
        # Step 3: Refresh snapshot (use current time as window)
        window_start = sample_ts - 60
        window_end = sample_ts + 1
        success = refresh_snapshot(conn, sensor_name, window_start, window_end)
        
        if not success:
            print("✗ Snapshot refresh failed (no samples found)")
            sys.exit(1)
        
        # Step 4: Verify updated_at changed
        final_updated_at = get_snapshot_updated_at(conn, sensor_name)
        print(f"Final snapshot updated_at: {final_updated_at}")
        
        if final_updated_at is None:
            print("✗ Snapshot not found after refresh")
            sys.exit(1)
        
        if initial_updated_at is not None and final_updated_at <= initial_updated_at:
            print(f"✗ Snapshot updated_at did not advance: {initial_updated_at} -> {final_updated_at}")
            sys.exit(1)
        
        print(f"✓ Snapshot updated_at advanced: {initial_updated_at} -> {final_updated_at}")
        print("✓ Smoke test PASSED")
        
        conn.close()
        
    except Exception as e:
        print(f"✗ Smoke test FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()

