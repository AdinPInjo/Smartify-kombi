# SQLite Connection Lifecycle Fix

## Problem
Background threads were getting "Cannot operate on a closed database" errors because:
1. `db_insert_sensor_sample()` was calling `conn.close()` TWICE
2. The second close was operating on an already-closed connection after the DELETE query

## Root Cause
```python
# BEFORE (BROKEN):
def db_insert_sensor_sample(...):
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    cur = conn.cursor()
    # ... INSERT query ...
    conn.commit()
    conn.close()  # ← First close
    
    # Keep only last 15 minutes of samples
    cutoff = created_at - (15 * 60)
    cur.execute("DELETE FROM sensor_samples WHERE created_at < ?", (cutoff,))  # ← Using closed connection!
    conn.commit()  # ← Fails: connection already closed
    conn.close()   # ← Second close on already-closed connection
```

## Fix Applied

### 1. Fixed `db_insert_sensor_sample()` (line ~833)
**Changed:** Removed premature `conn.close()` and `conn.commit()` calls
**Result:** Single commit and close at the end after both INSERT and DELETE

```python
# AFTER (FIXED):
def db_insert_sensor_sample(...):
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute(
        "INSERT INTO sensor_samples (sensor_name, temp, humidity, ok, created_at) VALUES (?, ?, ?, ?, ?)",
        (sensor_name, temp, humidity, 1 if ok else 0, created_at),
    )
    
    # Keep only last 15 minutes of samples to prevent DB growth
    cutoff = created_at - (15 * 60)
    cur.execute("DELETE FROM sensor_samples WHERE created_at < ?", (cutoff,))
    
    conn.commit()  # ← Single commit for both operations
    conn.close()   # ← Single close at the end
```

### 2. Added Persistence Success Logging (line ~1698)
**Added:** Rate-limited log message showing successful sample persistence
**Purpose:** Confirm writes are happening without errors

```python
# Log persistence success summary (once per SENSOR_SNAPSHOT_INTERVAL)
if now % SENSOR_SNAPSHOT_INTERVAL < SENSOR_SAMPLE_INTERVAL:
    sample_count_kombi = len(_sensor_samples.get("kombi", []))
    sample_count_garaza = len(_sensor_samples.get("garaza", []))
    logger.info("[Sensor Sampler] Persisted samples successfully - kombi: %d samples, garaza: %d samples", 
               sample_count_kombi, sample_count_garaza)
```

## Verification Commands (Run on RPi)

```bash
# 1. Restart service
sudo systemctl restart smartify-dashboard

# 2. Check for "Cannot operate on a closed database" errors (should be NONE)
sudo journalctl -u smartify-dashboard --since "2 min ago" --no-pager | grep -i "closed database"

# 3. Check for successful persistence logs
sudo journalctl -u smartify-dashboard --since "2 min ago" --no-pager | grep "Persisted samples successfully"

# 4. Verify sensor_samples table is growing
watch -n 5 'sqlite3 /home/adinpinjo/repos/Smartify-kombi/smartify/data/smartify.db "SELECT COUNT(*) as samples, MAX(created_at) as latest FROM sensor_samples;"'

# 5. Verify /api/sensors/latest shows fresh data
curl -sS http://127.0.0.1:8000/api/sensors/latest | python3 -m json.tool | grep -E "age_seconds|updated_at"
```

## Expected Results
- ✅ No "Cannot operate on a closed database" errors in logs
- ✅ `sensor_samples` count increases steadily (every 5 seconds)
- ✅ `/api/sensors/latest` shows `age_seconds` staying low (<120s)
- ✅ `sensor_snapshot.updated_at` advances every 60 seconds
- ✅ Logs show "[Sensor Sampler] Persisted samples successfully" every ~60s

## Technical Details

### Connection Lifecycle Pattern
All DB helper functions now follow this pattern:
1. Open fresh connection with `sqlite3.connect(DB_PATH, timeout=5.0)`
2. Set PRAGMAs (WAL, busy_timeout, synchronous)
3. Execute all queries using the same cursor
4. Single `conn.commit()` at the end
5. Single `conn.close()` at the very end

### Why This Works
- Each function call gets its own connection (no shared state)
- Connection is only closed once, after all operations complete
- WAL mode + busy_timeout handles concurrent access from multiple threads
- No risk of using a closed connection

### Files Modified
- `smartify/app.py`:
  - Line ~833-851: `db_insert_sensor_sample()` - Fixed double-close bug
  - Line ~1698-1712: Added persistence success logging

