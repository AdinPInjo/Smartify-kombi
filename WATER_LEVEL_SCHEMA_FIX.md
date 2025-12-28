# Water Level Schema & DB Lock Fixes

## Summary
Fixed critical issues after water level refactor:
1. **Schema mismatch**: `water_level_snapshot` table missing columns (`avg_signal_voltage`, etc.)
2. **DB lock errors**: Multiple threads writing without proper timeout/retry
3. **ADS1115 function call**: Wrong parameter names (`ch0`/`ch1` vs `channel0`/`channel1`)
4. **Test script import**: Failed to import `ads1115` module

## Changes Applied

### 1. `smartify/tools/test_ads_pair.py`
**Problem**: `ModuleNotFoundError: No module named 'ads1115'`

**Fix**:
- Changed from `import ads1115` to `from smartify import ads1115`
- Fixed parameter names: `ch0`/`ch1` → `channel0`/`channel1`
- Added repo root to sys.path for standalone execution

### 2. `smartify/water_level/reader.py`
**Problem**: `ads_read_voltage_pair() got an unexpected keyword argument 'ch0'`

**Fix**:
- Changed parameter names from `ch0`/`ch1` to `channel0`/`channel1` to match actual `ads1115.py` signature

```python
# OLD
v0, v1 = ads1115.ads_read_voltage_pair(ch0=signal_ch, ch1=supply_ch, ...)

# NEW
v0, v1 = ads1115.ads_read_voltage_pair(channel0=signal_ch, channel1=supply_ch, ...)
```

### 3. `smartify/water_level/db.py`
**Problem**: 
- `table water_level_snapshot has no column named avg_signal_voltage`
- DB lock errors from concurrent writes

**Fix**:
- **Schema migration**: Added `ALTER TABLE` logic in `db_init_water_level()` to add missing columns if table exists
- **Backward compatibility**: Supports both old (AUTOINCREMENT) and new (id=1 CHECK) schemas
- **Connection helper**: Created `_set_connection_pragmas()` to apply WAL + busy_timeout + synchronous=NORMAL
- **Robust upsert**: `db_upsert_water_snapshot()` now:
  - Detects which columns exist in schema
  - Only writes to existing columns
  - Tries id=1 upsert first, falls back to INSERT OR REPLACE for old schema
  - Sets PRAGMA on every connection
- **Flexible read**: `db_get_water_level_snapshot()` tries id=1 first, falls back to latest row

```python
# Migration in db_init_water_level()
cur.execute("PRAGMA table_info(water_level_snapshot)")
snapshot_columns = [row[1] for row in cur.fetchall()]

if snapshot_columns:  # Table exists
    missing_columns = {
        "avg_signal_voltage": "REAL",
        "avg_supply_div_voltage": "REAL",
        "supply_voltage_est": "REAL",
        "ratio": "REAL"
    }
    for col_name, col_type in missing_columns.items():
        if col_name not in snapshot_columns:
            cur.execute(f"ALTER TABLE water_level_snapshot ADD COLUMN {col_name} {col_type}")
```

### 4. `smartify/water_level/service.py`
**No changes needed** - already has retry logic from previous fix

### 5. `smartify/app.py`
**Problem**: Sensor sampler thread causing DB locks

**Fix**: Added timeout + PRAGMA + retry to all DB functions:
- `db_insert_temp()`: Added `timeout=5.0` + PRAGMA
- `db_insert_sensor_sample()`: Added `timeout=5.0` + PRAGMA
- `db_upsert_sensor_snapshot()`: Added `timeout=5.0` + PRAGMA + 3-attempt retry with backoff
- `db_get_sensor_snapshot()`: Added `timeout=5.0` + PRAGMA
- `db_insert_gps()`: Added `timeout=5.0` + PRAGMA
- `db_update_sensor_snapshot()`: Now aliases to `db_upsert_sensor_snapshot()`

```python
# Pattern applied to all DB writes
for retry in range(3):
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=NORMAL")
        # ... do work ...
        break
    except sqlite3.OperationalError as e:
        if "database is locked" in str(e) and retry < 2:
            print(f"[...] DB locked, retry {retry+1}/3...")
            time.sleep(0.1 * (retry + 1))
        else:
            print(f"[...] DB write failed: {e}")
```

## Testing

### Syntax Check
```bash
cd /Users/adinpinjo/repos/Smartify-kombi
python3 -m py_compile smartify/app.py smartify/water_level/*.py smartify/tools/test_ads_pair.py
# ✓ All files compile successfully
```

### On Raspberry Pi
```bash
# Deploy
cd ~/repos/Smartify-kombi
git pull

# Restart service
sudo systemctl restart smartify-dashboard.service
sudo systemctl status smartify-dashboard.service --no-pager

# Watch logs
journalctl -u smartify-dashboard.service -f

# Test endpoints
curl -s http://127.0.0.1:8000/api/water/settings | python3 -m json.tool
curl -s http://127.0.0.1:8000/api/water/level/live | python3 -m json.tool
curl -s http://127.0.0.1:8000/api/water/level/latest | python3 -m json.tool

# Test CLI tool
python3 smartify/tools/test_ads_pair.py
```

## Expected Results
1. ✅ No more "table has no column named avg_signal_voltage"
2. ✅ No more "database is locked" errors (or auto-retry with backoff)
3. ✅ `/api/water/level/live` returns valid readings or clear error
4. ✅ `/api/water/level/latest` returns valid JSON with snapshot
5. ✅ `test_ads_pair.py` runs without import errors
6. ✅ Logs show successful water level updates every 60 seconds

## DB Migration (Automatic)
On first startup after deploy:
1. `db_init_water_level()` detects existing table
2. Checks for missing columns via `PRAGMA table_info`
3. Runs `ALTER TABLE ... ADD COLUMN` for each missing column
4. Sets WAL mode and busy_timeout
5. All subsequent reads/writes use the new columns

**Safe**: If columns already exist, ALTER TABLE is skipped. If table doesn't exist, creates with full schema.

## Files Modified
- `smartify/tools/test_ads_pair.py` (import fix, parameter names)
- `smartify/water_level/reader.py` (parameter names)
- `smartify/water_level/db.py` (schema migration, PRAGMA helper, robust upsert)
- `smartify/app.py` (timeout + PRAGMA + retry for all sensor DB writes)

