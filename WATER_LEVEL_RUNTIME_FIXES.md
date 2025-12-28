# Water Level Final Fixes - Runtime Issues

## Summary
Fixed remaining runtime issues after water level refactor on Raspberry Pi:
1. ✅ **ADS1115 function signature**: Already correct (`channel0`/`channel1`)
2. ✅ **State object dict assignment**: Fixed all `app_state["key"]` to `app_state.key`
3. ✅ **PRAGMA settings**: Removed try/except wrapping to ensure they apply
4. ✅ **Error handling**: All DB operations already return valid responses

## Changes Applied

### 1. `smartify/water_level/service.py`
**Problem**: `'State' object does not support item assignment` - Starlette State requires attribute access, not dict-style access.

**Fix**: Changed all 5 occurrences of `app_state["water_level_latest"]` to `app_state.water_level_latest`:
- Line ~92: Error case (channel mismatch)
- Line ~196: Normalization mode success
- Line ~250: Voltage-only mode success
- Line ~307: I2C error with previous snapshot
- Line ~340: I2C error without previous snapshot

```python
# OLD (causes crash)
if app_state:
    app_state["water_level_latest"] = {...}

# NEW (correct)
if app_state is not None:
    if not hasattr(app_state, 'water_level_latest'):
        app_state.water_level_latest = {}
    app_state.water_level_latest = {...}
```

### 2. `smartify/water_level/db.py`
**Problem**: PRAGMA settings wrapped in try/except were silently failing, leaving `busy_timeout=0`.

**Fix**: Removed try/except wrapper in `_set_connection_pragmas()` and added verification:
```python
# OLD
try:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
except sqlite3.OperationalError:
    pass  # Silently failed!

# NEW
cur = conn.cursor()
cur.execute("PRAGMA journal_mode=WAL")
cur.execute("PRAGMA busy_timeout=5000")
cur.execute("PRAGMA synchronous=NORMAL")
# Verify
cur.execute("PRAGMA busy_timeout")
timeout = cur.fetchone()[0]
if timeout != 5000:
    print(f"[DB] Warning: busy_timeout is {timeout}, expected 5000")
```

### 3. `smartify/app.py`
**Problem**: Sensor sampler DB functions had try/except around PRAGMA, preventing them from applying.

**Fix**: Removed try/except wrappers in 5 functions:
- `db_upsert_sensor_snapshot()` - Line ~360
- `db_get_sensor_snapshot()` - Line ~390
- `db_insert_temp()` - Line ~323
- `db_insert_sensor_sample()` - Line ~334
- `db_insert_gps()` - Line ~407

```python
# OLD (in all 5 functions)
try:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
except sqlite3.OperationalError:
    pass  # Settings never applied!

# NEW
cur = conn.cursor()
cur.execute("PRAGMA journal_mode=WAL")
cur.execute("PRAGMA busy_timeout=5000")
cur.execute("PRAGMA synchronous=NORMAL")
```

### 4. ADS1115 Function Signature
**Status**: ✅ Already correct - No changes needed.

Verified `smartify/ads1115.py` signature:
```python
def ads_read_voltage_pair(
    channel0: int,  # ✓ Correct parameter name
    channel1: int,  # ✓ Correct parameter name
    ...
)
```

All callers in `smartify/water_level/reader.py` and `smartify/tools/test_ads_pair.py` already use `channel0`/`channel1` correctly (no `ch0`/`ch1` found).

### 5. API Error Handling
**Status**: ✅ Already correct - No changes needed.

Verified all water level API endpoints already return valid JSONResponse on all code paths (no empty responses possible).

## Testing

### Syntax Check
```bash
cd /Users/adinpinjo/repos/Smartify-kombi
python3 -m py_compile smartify/app.py smartify/water_level/*.py
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

# Verify PRAGMA settings applied
sqlite3 ~/repos/Smartify-kombi/smartify/data/smartify.db << 'EOF'
PRAGMA journal_mode;
PRAGMA busy_timeout;
PRAGMA synchronous;
EOF
# Should show: wal, 5000, 1 (NORMAL)

# Test endpoints
curl -s http://127.0.0.1:8000/api/water/level/live | python3 -m json.tool
curl -s http://127.0.0.1:8000/api/water/level/latest | python3 -m json.tool
```

## Expected Results After Deploy
1. ✅ No more `'State' object does not support item assignment` crashes
2. ✅ `PRAGMA busy_timeout` shows 5000 (not 0)
3. ✅ `PRAGMA synchronous` shows 1 or NORMAL (not 2/FULL)
4. ✅ Water level background thread stays running
5. ✅ `/api/water/level/live` returns valid JSON
6. ✅ `/api/water/level/latest` returns valid JSON
7. ✅ No "database is locked" errors (proper timeout + WAL + retry)
8. ✅ Logs show successful water level updates every 60 seconds

## Files Modified
- `smartify/water_level/service.py` (5 fixes: State object dict→attribute access)
- `smartify/water_level/db.py` (1 fix: PRAGMA helper unwrapped + verification)
- `smartify/app.py` (5 fixes: PRAGMA unwrapped in sensor DB functions)

## Minimal Diff Summary

**smartify/water_level/service.py** (5 locations):
- Lines ~92, ~196, ~250, ~307, ~340
- Changed: `app_state["water_level_latest"]` → `app_state.water_level_latest`
- Added: `if not hasattr(app_state, 'water_level_latest'): app_state.water_level_latest = {}`

**smartify/water_level/db.py** (1 location):
- Function: `_set_connection_pragmas()`
- Changed: Removed `try/except` wrapper, added `cur = conn.cursor()`, added verification

**smartify/app.py** (5 locations):
- Functions: `db_upsert_sensor_snapshot`, `db_get_sensor_snapshot`, `db_insert_temp`, `db_insert_sensor_sample`, `db_insert_gps`
- Changed: Removed `try/except` wrapper around PRAGMA statements, added `cur = conn.cursor()`

