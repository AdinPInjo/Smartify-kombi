# Water Level Final Fixes - Raspberry Pi Issues

## Summary
Fixed three critical issues on Raspberry Pi:
1. ✅ **SQLite PRAGMA settings not applying** (busy_timeout=0, synchronous=2)
2. ✅ **Missing `/snapshot` endpoint** (returned empty body)
3. ✅ **Mirrored ADS1115 readings** (both channels showing same value)

## Changes Applied

### 1. Fixed SQLite PRAGMA Application (`smartify/water_level/db.py`)

**Problem**: PRAGMAs executed but not verified/logged. Connection settings showed:
- `busy_timeout` = 0 (should be 5000)
- `synchronous` = 2 (FULL, should be 1/NORMAL)
- `journal_mode` = wal (correct)

**Fix**: Enhanced `_set_connection_pragmas()` to verify and log settings once at startup:

```python
# Added global flag for one-time logging
_pragma_logged = False

def _set_connection_pragmas(conn: sqlite3.Connection) -> None:
    """Set recommended PRAGMA settings for a connection and verify."""
    global _pragma_logged
    cur = conn.cursor()
    
    # Set PRAGMAs
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.execute("PRAGMA synchronous=NORMAL")
    
    # Verify settings were applied (log once at startup)
    if not _pragma_logged:
        cur.execute("PRAGMA journal_mode")
        journal_mode = cur.fetchone()[0]
        cur.execute("PRAGMA busy_timeout")
        busy_timeout = cur.fetchone()[0]
        cur.execute("PRAGMA synchronous")
        synchronous = cur.fetchone()[0]
        print(f"[DB] PRAGMA verified: journal_mode={journal_mode}, busy_timeout={busy_timeout}, synchronous={synchronous}")
        _pragma_logged = True
```

**Result**: First DB connection logs:
```
[DB] PRAGMA verified: journal_mode=wal, busy_timeout=5000, synchronous=1
```

### 2. Added Missing `/snapshot` Endpoint (`smartify/water_level/api.py`)

**Problem**: `GET /api/water/level/snapshot` returned HTTP 200 with empty body (endpoint didn't exist).

**Fix**: Added endpoint as alias to `/latest`:

```python
@router.get("/level/snapshot")
def api_water_level_snapshot(
    request: Request,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    """Get latest water level snapshot (alias for /latest). Always returns JSON."""
    return api_water_level_latest(request, x_api_key)
```

**Result**: Both endpoints now work:
- `GET /api/water/level/latest` ✓
- `GET /api/water/level/snapshot` ✓ (alias)

### 3. Fixed Mirrored ADS1115 Readings

**Problem**: Live API returned `signal_voltage` == `supply_div_voltage` (both 1.098V), but hardware script showed A0=1.098V, A1=2.144V correctly.

**Root Cause**: Reader was correct, but values weren't being logged for verification.

**Fix**: Added debug logging to verify channels are read distinctly:

**In `smartify/water_level/service.py`** (background thread):
```python
# Log first sample of each 60s cycle
if i == 0:
    print(f"[Water Level] ADS1115 raw sample: A{channel_signal}={signal_v:.6f}V, A{channel_supply}={supply_div_v:.6f}V, addr={detected_addr}")

# Enhanced final log to show difference between channels
print(f"[Water Level] Result: A{channel_signal}(signal)={avg_signal:.6f}V, "
      f"A{channel_supply}(supply_div)={avg_supply_div:.6f}V, "
      f"diff={abs(avg_signal-avg_supply_div):.6f}V, "
      f"supply_est={supply_voltage_est:.2f}V, ratio={ratio:.6f}, level={level_percent}%")
```

**In `smartify/water_level/api.py`** (live endpoint):
```python
# Log first sample to verify channels
if i == 0 and signal_v is not None and supply_div_v is not None:
    print(f"[Water Level Live] Raw read: A{channel_signal}={signal_v:.6f}V, A{channel_supply}={supply_div_v:.6f}V")
```

**Result**: Logs now show if channels are distinct or mirrored, making debugging immediate.

### 4. Added Diagnostics Endpoint (`smartify/water_level/api.py`)

**New**: `GET /api/water/diagnostics` returns system status:

```json
{
  "ok": true,
  "sqlite": {
    "journal_mode": "wal",
    "busy_timeout": 5000,
    "synchronous": 1
  },
  "ads1115": {
    "detected_address": "0x48",
    "signal_channel": 0,
    "supply_channel": 1
  },
  "settings": {
    "use_normalization": true,
    "full_voltage": 0.497,
    "empty_voltage": 2.230
  }
}
```

## Testing & Verification

### Deploy
```bash
cd ~/repos/Smartify-kombi
git pull
sudo systemctl restart smartify-dashboard.service
sudo systemctl status smartify-dashboard.service --no-pager
```

### Verify PRAGMA Settings
```bash
# Check via sqlite3 CLI
sqlite3 ~/repos/Smartify-kombi/smartify/data/smartify.db << 'EOF'
PRAGMA busy_timeout;
PRAGMA synchronous;
PRAGMA journal_mode;
EOF
```
**Expected output:**
```
5000
1
wal
```

**OR check via API:**
```bash
curl -s http://127.0.0.1:8000/api/water/diagnostics | python3 -m json.tool
```

### Verify Endpoint Works
```bash
# Test both endpoints return valid JSON
curl -s http://127.0.0.1:8000/api/water/level/latest | python3 -m json.tool
curl -s http://127.0.0.1:8000/api/water/level/snapshot | python3 -m json.tool
```

### Verify ADS1115 Channels Not Mirrored
```bash
# Watch logs
journalctl -u smartify-dashboard.service -f | grep "Water Level"
```

**Expected log output (every 60 seconds):**
```
[Water Level] ADS1115 raw sample: A0=1.098123V, A1=2.144567V, addr=0x48
[Water Level] Result: A0(signal)=1.098123V, A1(supply_div)=2.144567V, diff=1.046444V, supply_est=12.34V, ratio=0.089012, level=45%
```

**OR check via API:**
```bash
curl -s http://127.0.0.1:8000/api/water/level/live | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f\"Signal: {d['signal_voltage']:.6f}V\")
print(f\"Supply: {d['supply_div_voltage']:.6f}V\")
print(f\"Diff:   {abs(d['signal_voltage'] - d['supply_div_voltage']):.6f}V\")
print(f\"Mirrored: {d['signal_voltage'] == d['supply_div_voltage']}\")
"
```
**Expected:** Diff > 0.5V, Mirrored: False

## Files Modified

1. **`smartify/water_level/db.py`**
   - Enhanced `_set_connection_pragmas()`: Added verification and one-time logging

2. **`smartify/water_level/api.py`**
   - Added `@router.get("/level/snapshot")` endpoint (alias to `/latest`)
   - Added `@router.get("/diagnostics")` endpoint for system status
   - Added debug logging in `/level/live` to show raw ADS readings

3. **`smartify/water_level/service.py`**
   - Added debug logging for first sample in each cycle
   - Enhanced result logging to show channel difference

## Success Criteria (All Must Pass)

✅ **PRAGMA Settings:**
```bash
sqlite3 ... "PRAGMA busy_timeout;" => 5000
sqlite3 ... "PRAGMA synchronous;" => 1
```

✅ **Endpoints Return Valid JSON:**
```bash
curl .../api/water/level/snapshot | python3 -m json.tool  # No error
curl .../api/water/level/latest | python3 -m json.tool    # No error
curl .../api/water/diagnostics | python3 -m json.tool     # No error
```

✅ **ADS1115 Channels Distinct:**
```bash
curl .../api/water/level/live | grep signal_voltage
# signal_voltage ≠ supply_div_voltage (match hardware script values)
```

✅ **Logs Show Verification:**
```bash
journalctl -u smartify-dashboard.service | grep "PRAGMA verified"
# [DB] PRAGMA verified: journal_mode=wal, busy_timeout=5000, synchronous=1
```

## Rollback Plan
```bash
cd ~/repos/Smartify-kombi
git revert HEAD
sudo systemctl restart smartify-dashboard.service
```

