#!/usr/bin/env python3
"""Fix critical indentation errors in with db_connect() blocks"""

with open("smartify/app.py", "r") as f:
    content = f.read()

# Fix db_insert_temp
content = content.replace(
    """def db_insert_temp(ts: int, sensor_index: int, t: Optional[float], h: Optional[float]) -> None:
    with db_connect() as conn:
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO temperature_readings (ts, sensor_index, temperature_c, humidity) VALUES (?, ?, ?, ?)",
        (ts, sensor_index, t, h),
    )
    conn.commit()""",
    """def db_insert_temp(ts: int, sensor_index: int, t: Optional[float], h: Optional[float]) -> None:
    with db_connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO temperature_readings (ts, sensor_index, temperature_c, humidity) VALUES (?, ?, ?, ?)",
            (ts, sensor_index, t, h),
        )
        conn.commit()"""
)

# Fix db_insert_sensor_sample  
content = content.replace(
    """def db_insert_sensor_sample(sensor_name: str, temp: Optional[float], humidity: Optional[float], ok: bool, created_at: int) -> None:
    \"\"\"Insert a raw sensor sample. Each call opens its own connection.\"\"\"
    with db_connect() as conn:
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO sensor_samples (sensor_name, temp, humidity, ok, created_at) VALUES (?, ?, ?, ?, ?)",
        (sensor_name, temp, humidity, 1 if ok else 0, created_at),
    )
    
    # Keep only last 15 minutes of samples to prevent DB growth
    cutoff = created_at - (15 * 60)
    cur.execute("DELETE FROM sensor_samples WHERE created_at < ?", (cutoff,))
        
    conn.commit()""",
    """def db_insert_sensor_sample(sensor_name: str, temp: Optional[float], humidity: Optional[float], ok: bool, created_at: int) -> None:
    \"\"\"Insert a raw sensor sample. Each call opens its own connection.\"\"\"
    with db_connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO sensor_samples (sensor_name, temp, humidity, ok, created_at) VALUES (?, ?, ?, ?, ?)",
            (sensor_name, temp, humidity, 1 if ok else 0, created_at),
        )
        
        # Keep only last 15 minutes of samples to prevent DB growth
        cutoff = created_at - (15 * 60)
        cur.execute("DELETE FROM sensor_samples WHERE created_at < ?", (cutoff,))
        
        conn.commit()"""
)

# Fix db_get_sensor_snapshot
content = content.replace(
    """def db_get_sensor_snapshot(sensor_name: str) -> Optional[Dict[str, Any]]:
    \"\"\"Get sensor snapshot. Uses fresh connection per call.\"\"\"
    with db_connect() as conn:
    cur = conn.cursor()
    cur.execute("SELECT * FROM sensor_snapshot WHERE sensor_name = ?", (sensor_name,))
    row = cur.fetchone()
    return dict(row) if row else None""",
    """def db_get_sensor_snapshot(sensor_name: str) -> Optional[Dict[str, Any]]:
    \"\"\"Get sensor snapshot. Uses fresh connection per call.\"\"\"
    with db_connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM sensor_snapshot WHERE sensor_name = ?", (sensor_name,))
        row = cur.fetchone()
        return dict(row) if row else None"""
)

with open("smartify/app.py", "w") as f:
    f.write(content)

print("✅ Fixed indentation in 3 functions")
print("   - db_insert_temp()")
print("   - db_insert_sensor_sample()")
print("   - db_get_sensor_snapshot()")

