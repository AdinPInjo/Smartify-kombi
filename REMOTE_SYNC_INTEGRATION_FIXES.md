# ✅ Remote Sync Integration Fixes Complete

## Summary of Changes

All integration issues have been fixed in the Smartify-kombi remote sync module.

## 1. Systemd User Handling ✅

**Problem:** Service file hardcoded `User=pi` and `Group=pi`

**Solution:**
- Updated `deploy/smartify-remote-sync.service` to use placeholders: `__USER__` and `__WORKING_DIR__`
- Updated `deploy/install_remote_sync.sh` to:
  - Detect actual user via `$SUDO_USER`, `$LOGNAME`, or `logname`
  - Substitute placeholders with detected user and actual smartify directory
  - Create directories with proper ownership for detected user
  
**Result:** Service now runs as the actual user, not hardcoded `pi`

## 2. Typo Fix ✅

**Problem:** No typo found in codebase

**Result:** Verified no `wate_percent` typo exists (already correct as `water_percent`)

## 3. Sensor Adapters with HTTP API Fallback ✅

**Problem:** Adapters had placeholder imports that would fail if modules not available

**Solution:** Complete rewrite of `remote_sync/adapters.py`:

### Temperature Adapter
**Primary:** Direct import from `smartify.temp_logger`
**Fallback:** `GET /api/temperature/latest`
- Averages all sensor temperatures from `sensors[].temperature_c`
- Supports alternative key: `temp_c`
- Clear logging when None

### Water Level Adapter
**Primary:** Direct import from `smartify.water_level.reader.WaterLevelReader`
**Fallback:** `GET /api/water/level/live`
- Tries keys in order: `level_percent`, `water_percent`, `percent`, `percentage`
- Logs API status and error messages
- Clear logging when None

### GPS Adapter
**Primary:** Direct import from `smartify.gps_logger`
**Fallback:** `GET /api/gps/current`
- Checks `ok` field (skips if false)
- Extracts `lat` and `lon`
- Clear logging when None

**Configuration:**
```bash
export SMARTIFY_LOCAL_API_BASE="http://127.0.0.1:8000"
```

## 4. Environment Variables in Service File ✅

Added to `deploy/smartify-remote-sync.service`:

```ini
Environment="SMARTIFY_REMOTE_MODE=local"
Environment="SMARTIFY_LOCAL_API_BASE=http://127.0.0.1:8000"
```

**Note:** The Smartify API runs on port **8000** (uvicorn default).

## 5. API Documentation ✅

Added comprehensive API endpoint documentation to `remote_sync/README.md`:

### Expected Endpoints

1. **Temperature:** `GET /api/temperature/latest`
   ```json
   {
     "ts": 1705419600,
     "sensors": [
       {"sensor_name": "kombi", "temperature_c": 22.5, "humidity": 45.2},
       {"sensor_name": "garaza", "temperature_c": 18.2, "humidity": 52.8}
     ]
   }
   ```

2. **Water Level:** `GET /api/water/level/live`
   ```json
   {
     "ok": true,
     "level_percent": 68,
     "signal_voltage": 1.234,
     "ratio": 0.127,
     "status": "ok"
   }
   ```

3. **GPS:** `GET /api/gps/current`
   ```json
   {
     "ts": 1705419600,
     "lat": 48.8566,
     "lon": 2.3522,
     "speed_kmh": 45.5,
     "ok": true
   }
   ```

## Installation Commands

### Fresh Install

```bash
cd /home/pi/Smartify-kombi
bash smartify/deploy/install_remote_sync.sh
```

The script will:
1. Detect your actual username (works with or without sudo)
2. Create directories with proper permissions
3. Install service with correct user substitution
4. Enable and optionally start the service

### Reinstall (If Already Installed)

```bash
# Stop and disable old service
sudo systemctl stop smartify-remote-sync
sudo systemctl disable smartify-remote-sync

# Remove old service file
sudo rm /etc/systemd/system/smartify-remote-sync.service

# Reload systemd
sudo systemctl daemon-reload

# Run fresh install
cd /home/pi/Smartify-kombi
bash smartify/deploy/install_remote_sync.sh
```

## Verification Commands

### 1. Check Service Status

```bash
# Is service running?
sudo systemctl status smartify-remote-sync

# Check which user it's running as
ps aux | grep "remote_sync/runner.py"
```

### 2. Check Logs for Sensor Readings

```bash
# View recent logs
sudo journalctl -u smartify-remote-sync -n 50

# Follow live logs
tail -f /var/log/smartify/remote_sync.log

# Look for sensor readings in logs
grep "temperature\|water\|GPS" /var/log/smartify/remote_sync.log | tail -20
```

### 3. Verify Telemetry Contains Real Data

```bash
# View last telemetry entry
tail -1 /var/log/smartify/telemetry_outbox.jsonl | jq

# Check if temperature_c and water_percent are NOT null
tail -10 /var/log/smartify/telemetry_outbox.jsonl | jq '{temperature_c, water_percent, delta_km, ts}'

# Expected output (values should NOT be null if sensors are working):
# {
#   "temperature_c": 22.5,
#   "water_percent": 68.0,
#   "delta_km": 0.0,
#   "ts": "2026-01-16T15:30:45.123456"
# }
```

### 4. Check API Fallback Behavior

```bash
# Test if API endpoints are accessible (port 8000 is default)
curl http://127.0.0.1:8000/api/temperature/latest
curl http://127.0.0.1:8000/api/water/level/live
curl http://127.0.0.1:8000/api/gps/current

# Check logs for "HTTP API" messages
grep "HTTP API" /var/log/smartify/remote_sync.log | tail -10
```

### 5. Verify Sensor Method Used

Look for these log patterns:

**Direct Import (Preferred):**
```
Temperature from direct import: 22.5°C
Water level from direct import: 68%
GPS from direct import: 48.8566, 2.3522
```

**HTTP API Fallback:**
```
temp_logger not available, trying HTTP API
Temperature from HTTP API: 22.5°C (avg of 2 sensors)
```

**Errors (Check Configuration):**
```
HTTP API request failed: Connection refused
HTTP API returned no valid temperature readings
```

## Troubleshooting

### No Temperature Data

```bash
# Check if temperature API works (port 8000 is default)
curl http://127.0.0.1:8000/api/temperature/latest | jq

# Check if app is running
sudo systemctl status smartify-app

# Check adapter logs
grep "temperature" /var/log/smartify/remote_sync.log | tail -20
```

### No Water Level Data

```bash
# Check if water API works (port 8000 is default)
curl http://127.0.0.1:8000/api/water/level/live | jq

# Check if level_percent is in response
curl -s http://127.0.0.1:8000/api/water/level/live | jq '.level_percent'

# Check adapter logs
grep "water" /var/log/smartify/remote_sync.log | tail -20
```

### Service Won't Start

```bash
# Check for errors
sudo journalctl -u smartify-remote-sync -n 100

# Check if directories exist
ls -la /var/log/smartify/
ls -la /var/lib/smartify/
ls -la /etc/smartify/

# Check permissions
ls -la /var/log/smartify/ | grep "$(whoami)"
```

### Wrong User Running Service

```bash
# Check current user in service
ps aux | grep "remote_sync/runner.py"

# Check service file
sudo cat /etc/systemd/system/smartify-remote-sync.service | grep "User="

# If wrong, reinstall:
sudo systemctl stop smartify-remote-sync
sudo rm /etc/systemd/system/smartify-remote-sync.service
cd /home/pi/Smartify-kombi
bash smartify/deploy/install_remote_sync.sh
```

## Expected Behavior After Fixes

### Startup (First 2 Minutes)

```bash
# Watch logs live
tail -f /var/log/smartify/remote_sync.log
```

**Expected output:**
```
2026-01-16 15:30:00 - __main__ - INFO - Smartify Remote Sync starting...
2026-01-16 15:30:00 - __main__ - INFO - Mode: local
2026-01-16 15:30:00 - __main__ - INFO - All components initialized successfully
2026-01-16 15:30:00 - __main__ - INFO - All loops started, running...
2026-01-16 15:30:00 - __main__ - INFO - Starting telemetry loop (interval=60s)
2026-01-16 15:30:00 - __main__ - INFO - Starting settings loop (interval=15s)
2026-01-16 15:30:45 - __main__ - INFO - Posting telemetry: temp=22.5, water=68.0, delta_km=None, gps=no
2026-01-16 15:30:45 - __main__ - INFO - Telemetry posted successfully
```

### Telemetry File (After 1 Minute)

```bash
tail -1 /var/log/smartify/telemetry_outbox.jsonl | jq
```

**Expected output (real data, not null):**
```json
{
  "ts": "2026-01-16T15:30:45.123456",
  "temperature_c": 22.5,
  "water_percent": 68.0,
  "delta_km": null,
  "gps_lat": null,
  "gps_lon": null
}
```

**NOT this (all null would indicate sensor reading failure):**
```json
{
  "ts": "2026-01-16T15:30:45.123456"
}
```

## Files Changed

```
smartify/
├── remote_sync/
│   ├── adapters.py               ← Rewritten with HTTP API fallback
│   └── README.md                 ← Added API endpoint docs
└── deploy/
    ├── smartify-remote-sync.service  ← Added env vars, user placeholders
    └── install_remote_sync.sh        ← User detection & substitution
```

## Summary Checklist

- ✅ Service file uses detected user (not hardcoded pi)
- ✅ Install script detects actual user via $SUDO_USER/logname
- ✅ No typo (water_percent already correct)
- ✅ Temperature adapter with HTTP fallback
- ✅ Water level adapter with HTTP fallback (tries multiple keys)
- ✅ GPS adapter with HTTP fallback
- ✅ Environment variables in service file
- ✅ Clear logging when values are None
- ✅ API endpoint documentation in README
- ✅ Verification commands provided

**All integration issues resolved!** 🎉

