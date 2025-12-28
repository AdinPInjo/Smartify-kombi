# Water Level System Stability Fixes

## Summary
Fixed critical issues after refactoring water level code into `smartify/water_level/*` module:
1. **ADS1115 import failures** - module not available under systemd
2. **SQLite database locking** - DELETE+INSERT causing contention
3. **Missing error handling** - background thread crashes on DB errors
4. **Better error messages** - distinguish import vs I2C hardware failures

## Changes Applied

### 1. `smartify/water_level/reader.py`
**Problem**: Import `ads1115` failed under systemd, causing "module not available" errors.

**Fix**:
- Changed from `import ads1115` to `from smartify import ads1115` (absolute import)
- Added traceback logging on import failure for better debugging
- Fixed function call parameter names: `channel0`/`channel1` → `ch0`/`ch1`

```python
# OLD
try:
    import ads1115
except ImportError:
    ads1115 = None

# NEW
try:
    from smartify import ads1115
except ImportError as e:
    print(f"[Water Level Reader] CRITICAL: Failed to import ads1115 module: {e}")
    import traceback
    traceback.print_exc()
    ads1115 = None
```

---

### 2. `smartify/water_level/db.py`
**Problem**: `DELETE FROM water_level_snapshot` + `INSERT` caused database locks.

**Fix**:
- Changed snapshot table schema to single-row pattern with `id=1` constraint
- Replaced DELETE+INSERT with single `INSERT ... ON CONFLICT DO UPDATE` (upsert)
- Added WAL mode and busy_timeout at DB init for better concurrency
- Changed query from `ORDER BY updated_at DESC LIMIT 1` to `WHERE id = 1`

```python
# Schema change
CREATE TABLE water_level_snapshot (
    id INTEGER PRIMARY KEY CHECK(id=1),  -- Single row constraint
    ...
);

# Upsert pattern
INSERT INTO water_level_snapshot (id, ...) VALUES (1, ...)
ON CONFLICT(id) DO UPDATE SET
    avg_voltage = excluded.avg_voltage,
    ...
```

---

### 3. `smartify/water_level/service.py`
**Problem**: Background thread crashed on DB locks, no retry logic.

**Fix**:
- Added `sqlite3.connect(str(db_path), timeout=5.0)` for all connections
- Wrapped all DB writes in retry loop (3 attempts, exponential backoff)
- Added in-memory `last_good_snapshot` fallback
- Added import check for `ads1115` module to improve error messages
- Replaced all `db_insert_water_snapshot` calls with `db_upsert_water_snapshot`

```python
# Retry pattern for DB writes
for retry in range(3):
    try:
        conn = sqlite3.connect(str(db_path), timeout=5.0)
        water_db.db_upsert_water_snapshot(conn, snapshot)
        conn.close()
        last_good_snapshot = snapshot.copy()
        break
    except sqlite3.OperationalError as e:
        if "database is locked" in str(e) and retry < 2:
            print(f"[Water Level] DB locked, retry {retry+1}/3...")
            time.sleep(0.5 * (retry + 1))
        else:
            print(f"[Water Level] DB write failed after retries: {e}")
            # Continue with in-memory snapshot only
```

---

## Testing

### Syntax Check
```bash
cd /Users/adinpinjo/repos/Smartify-kombi
python3 -m py_compile smartify/water_level/reader.py smartify/water_level/db.py smartify/water_level/service.py
# ✓ All modules compile OK
```

### On Raspberry Pi
```bash
# Deploy changes
cd ~/repos/Smartify-kombi
git pull

# Restart service
sudo systemctl restart smartify-dashboard.service
sudo systemctl status smartify-dashboard.service --no-pager

# Check logs
journalctl -u smartify-dashboard.service -f

# Test API endpoints
curl -s http://127.0.0.1:8000/api/water/settings | python3 -m json.tool
curl -s http://127.0.0.1:8000/api/water/level/live | python3 -m json.tool
curl -s http://127.0.0.1:8000/api/water/level/latest | python3 -m json.tool
```

### Expected Results
1. **No more "ads1115 module not available"** errors (unless actual import failure, then with traceback)
2. **No more "database is locked"** errors (or auto-retry with backoff)
3. **API responses always return valid JSON** with `ok`, `status`, and data fields
4. **Background thread stays running** even on transient DB lock errors
5. **Live endpoint returns clear error messages**: "ADS1115 module not available" vs "I2C read error"

---

## DB Migration (Automatic on Startup)
The new single-row upsert pattern is backward compatible. On first startup after deploy:
- Existing multi-row table will be queried with `WHERE id = 1` (may return NULL initially)
- First upsert will create the `id=1` row
- Old rows (if any) are ignored but not deleted (safe)

To manually clean old rows (optional):
```sql
DELETE FROM water_level_snapshot WHERE id != 1;
```

---

## Rollback Plan
If issues occur:
```bash
cd ~/repos/Smartify-kombi
git revert HEAD
sudo systemctl restart smartify-dashboard.service
```

---

## Files Modified
- `smartify/water_level/reader.py` (import fix, parameter name fix)
- `smartify/water_level/db.py` (upsert pattern, WAL mode, query change)
- `smartify/water_level/service.py` (retry logic, timeout, fallback, import check)

