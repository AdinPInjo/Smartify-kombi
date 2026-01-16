# Enriched Telemetry & Remote Settings - Final Implementation

## Overview

Implemented comprehensive device state tracking, GPS-based distance calculation with safety filters, and remote settings application with heater automation - all while maintaining backward compatibility and respecting privacy constraints.

---

## ✅ Tasks Completed

### TASK 1: Enriched Telemetry Upload ✅

**Implementation**:
- Telemetry continues to post every 60 seconds
- `telemetry.temperature_c` stores average temperature (backward compatible)
- `telemetry.water_percent` stores water level
- `telemetry.delta_km` stores distance traveled (with safety filters)
- **GPS coordinates are NOT written to telemetry table** (privacy requirement)

**Key Changes**:
- Modified telemetry loop to explicitly set `gps_lat=None, gps_lon=None` when posting
- GPS coordinates only go to `device_state.current_state` (admin-only)

### TASK 2: Enriched device_state.current_state ✅

**Implementation**:
- After each telemetry post, upsert `device_state` with rich snapshot
- Structure matches requirements:

```json
{
  "gps": null,  // or {"lat": 43.86, "lon": 18.41, "fix": true, "speed_kmh": 0.0}
  "temps": {"t1": 22.4, "t2": 23.0, "avg": 22.7},
  "relays": {"heater": "on", "pump": "off"},
  "water_percent": 74.0,
  "uptime_s": 123456
}
```

**Key Changes**:
- `build_current_state()` now returns GPS as `null` if no fix
- GPS object includes detailed metadata (fix, speed_kmh, sats, hdop) when available
- All fields properly handle None values
- Stored via `ackState` call after telemetry post

### TASK 3: Relay Status Upload + Control ✅

**Implementation**:
- `read_relay_states()` reads from `/api/relays` endpoint
- Returns dictionary: `{"heater": {"state": "on", "mode": "auto", ...}}`
- `set_relay_state(relay_name, state)` generic control function
- Calls `/api/relays/{relay_id}/state` endpoint
- Robust error handling: failures log warnings but don't crash

**Key Changes**:
- All relay control functions use HTTP API
- Failures are logged but loops continue
- Relay states included in `current_state.relays`

### TASK 4: Remote desired_state Polling + Application ✅

**Implementation**:
- Settings loop polls `getDesiredState` every 15 seconds
- Version-based application: only apply if `remote_version > local_version`
- After applying, calls `ackState` with applied version + current_state
- Supports all required fields:
  - `heater_force`: "auto" | "on" | "off"
  - `heater_auto`: boolean
  - `heater_on_below_c`: number
  - `heater_off_above_c`: number
  - `pump_force`: "on" | "off"
  - `lights_mode`: "off" | "dim" | "on"
  - `relay_rules`: (future-proof, ignored if missing)

**Key Changes**:
- Settings loop passes `state_manager` to `apply_desired_state()`
- Actions logged to `current_state.actions_taken` array
- Clear logging of what changed and why

### TASK 5: Heater Automation Rules ✅

**Implementation**:
- **Force modes**:
  - `heater_force == "on"`: Force relay ON
  - `heater_force == "off"`: Force relay OFF
  - `heater_force == "auto"` + `heater_auto == true`: Use thresholds

- **Automatic control**:
  - Turn ON if `avg_temp < heater_on_below_c`
  - Turn OFF if `avg_temp > heater_off_above_c`
  - HOLD (no change) if in hysteresis range

- **Safety features**:
  - Validates thresholds: `on_below < off_above` (ignores if invalid)
  - **Minimum hold time**: 5 minutes between state changes (prevents oscillation)
  - Only changes state if actually different from current
  - Logs hold time blocking clearly

**Key Changes**:
- `apply_desired_state()` now accepts `state_manager` parameter
- Tracks last relay change time in `/var/lib/smartify/last_relay_change.json`
- Enforces 5-minute minimum hold time
- Comprehensive action logging

**Example logs**:
```
INFO - Actions: heater auto ON (temp 4.5°C < 5.0°C)
INFO - Actions: heater auto HOLD (temp 22.7°C in range [5.0°C - 23.0°C])
INFO - Actions: heater auto ON (blocked: 180s hold time)
```

### TASK 6: Kilometers / km_year (PUBLIC) ✅

**Implementation**:
- `delta_km` calculated with comprehensive safety checks:
  - **Both fixes must be valid** (GPS fix available)
  - **Time delta <= 10 minutes** (resets baseline if longer)
  - **Speed sanity check** (< 180 km/h, ignores if exceeded)
  - **Jitter filter** (< 30 meters ignored to prevent accumulation)
  
- **Persistent GPS fix storage**:
  - Saved to `/var/lib/smartify/last_gps_fix.json`
  - Structure: `{"ts": 1737036000, "lat": 43.86, "lon": 18.41}`
  - Survives restarts

- **Privacy compliance**:
  - GPS coordinates **NEVER** in telemetry table
  - GPS coordinates **ONLY** in `device_state.current_state` (admin-only)
  - Public view `public_latest` shows only `km_year` (sum of delta_km)

**Key Changes**:
- New function: `calculate_delta_km_safe()` with all safety checks
- StateManager now has `get_last_gps_fix()` and `save_last_gps_fix()`
- Telemetry loop explicitly passes `gps_lat=None, gps_lon=None`
- Detailed logging of GPS movement and filtering

**Example logs**:
```
DEBUG - Valid delta_km: 1.234 km (speed: 45.2 km/h, time: 98s)
DEBUG - Filtering GPS jitter: 12.5m < 30m threshold
WARNING - Unrealistic speed detected: 250.0 km/h, ignoring delta_km
DEBUG - Time delta too large (720s), resetting GPS baseline
```

---

## Files Changed

### smartify/remote_sync/adapters.py

**Enhanced GPS reading**:
- `read_gps_location()` now returns detailed GPS object with fix, speed, metadata
- Returns `None` if no fix (not partial data)
- Validates coordinate ranges

**Enhanced current_state builder**:
- `build_current_state()` returns GPS as `null` if no fix
- GPS object includes all available metadata
- Properly handles all None values
- Structure matches admin-only requirements

**Enhanced heater automation**:
- `apply_desired_state()` accepts `state_manager` parameter
- Validates thresholds (on_below < off_above)
- Enforces 5-minute minimum hold time
- Checks current state before changing
- Comprehensive action logging
- Reads current relay states to determine if change needed

### smartify/remote_sync/runner.py

**Enhanced StateManager**:
- Renamed `last_gps.json` → `last_gps_fix.json` (clearer naming)
- New structure: `{"ts": unix_timestamp, "lat": float, "lon": float}`
- Added `get_last_relay_change()` and `save_relay_change()` for hold time tracking
- Stores relay change times in `/var/lib/smartify/last_relay_change.json`

**New function: calculate_delta_km_safe()**:
- Implements all TASK 6 safety checks
- Time delta validation (<= 10 minutes)
- Speed sanity check (< 180 km/h)
- Jitter filter (< 30 meters)
- Detailed logging of filtering reasons

**Enhanced telemetry loop**:
- Uses `calculate_delta_km_safe()` for delta_km calculation
- Saves GPS fix with timestamp
- Explicitly passes `gps_lat=None, gps_lon=None` to telemetry
- GPS coordinates only in `device_state.current_state`
- Logs GPS fix status and movement

**Enhanced settings loop**:
- Passes `state_manager` to `apply_desired_state()`
- Logs actions taken
- Logs relay states after changes

---

## Backward Compatibility

✅ **NO BREAKING CHANGES**:

1. **Telemetry table unchanged**:
   - Still stores `temperature_c` (average)
   - Still stores `water_percent`
   - Still stores `delta_km` (now with safety filters)
   - NO GPS coordinates in telemetry (privacy requirement)

2. **Existing dashboards work**:
   - Public dashboard reads `public_latest` view
   - `km_year` calculated from `SUM(delta_km)` since Jan 1
   - No GPS coordinates exposed publicly

3. **Local mode unchanged**:
   - Still writes to `telemetry_outbox.jsonl`
   - Still reads from `desired_state.json`
   - Still writes to `ack_state.json`
   - New fields appear in files but don't break anything

---

## Privacy & Security

✅ **GPS Privacy Enforced**:

1. **Public view** (`public_latest`):
   - Shows only `km_year` (aggregated distance)
   - NO GPS coordinates
   - NO individual telemetry GPS data

2. **Admin view** (`device_state.current_state`):
   - GPS coordinates available (for admin only)
   - Includes fix quality metadata
   - Requires authentication

3. **Telemetry table**:
   - NO GPS coordinates stored
   - Only `delta_km` (distance, not location)

---

## Safety Features

### GPS Distance Calculation

✅ **Prevents jitter accumulation**:
- Filters movements < 30 meters
- Ignores unrealistic speeds (> 180 km/h)
- Resets baseline if time gap > 10 minutes
- Validates coordinate ranges

✅ **Robust error handling**:
- Handles missing GPS gracefully
- Never crashes on invalid data
- Logs filtering reasons clearly

### Heater Automation

✅ **Prevents oscillation**:
- 5-minute minimum hold time between changes
- Hysteresis range (on_below < off_above)
- Only changes if state actually differs
- Validates thresholds before applying

✅ **Safe defaults**:
- Invalid config ignored (logged)
- Temperature unavailable → no change
- Force modes override auto safely

---

## Verification Checklist

### 1. Telemetry Still Posts ✅
```bash
tail -f /var/log/smartify/remote_sync.log
# Look for: "Telemetry posted successfully"
```

### 2. device_state.current_state Updated ✅
```bash
# Local mode
cat /var/log/smartify/ack_state.json | jq '.current_state'

# HTTP mode (Supabase)
SELECT current_state FROM device_state WHERE device_id = 'YOUR_ID';
```

**Expected**:
```json
{
  "gps": null,  // or GPS object if fix
  "temps": {"t1": 22.4, "t2": 23.0, "avg": 22.7},
  "relays": {"heater": "on"},
  "water_percent": 74.0,
  "uptime_s": 123456
}
```

### 3. Settings Applied Within ~15s ✅
```bash
# Edit desired_state (local mode)
sudo nano /etc/smartify/desired_state.json
# Set: {"version": 2, "desired_state": {"heater_auto": true, "heater_on_below_c": 25.0}}

# Watch logs
tail -f /var/log/smartify/remote_sync.log
# Look for: "New settings version 2 detected, applying..."
# Look for: "Actions: heater auto ON (temp X°C < 25.0°C)"
```

### 4. km_year Increases Only on Real Movement ✅
```bash
# Check telemetry for delta_km
tail /var/log/smartify/telemetry_outbox.jsonl | jq '.delta_km'

# Should see:
# - null when no GPS fix
# - null when jitter filtered
# - actual km values when moving
```

**Test jitter filter**:
- Stay in one location (house)
- GPS may drift slightly
- `delta_km` should remain `null` (< 30m movements filtered)

**Test real movement**:
- Drive ~1 km
- Next telemetry post should show `delta_km` ≈ 1.0

### 5. Public View Has NO GPS ✅
```sql
-- Public view should NOT have GPS columns
SELECT * FROM public_latest;
-- Should show: device_id, ts, temperature_c, water_percent, km_year
-- Should NOT show: gps_lat, gps_lon
```

### 6. Heater Hold Time Works ✅
```bash
# Set heater to auto with low threshold
# Heater turns on
# Immediately change threshold to force off
# Should see: "heater change blocked by hold time: XXXs remaining"
# Wait 5 minutes
# Change should apply
```

---

## Example Logs

### Successful Telemetry Post with GPS
```
INFO - Posting telemetry: temp=22.7, water=74.0, delta_km=1.234, gps_fix=yes
DEBUG - Valid delta_km: 1.234 km (speed: 45.2 km/h, time: 98s)
INFO - GPS movement: 1.234 km
INFO - Telemetry posted successfully
INFO - Device state updated
DEBUG - State: relays={'heater': 'on'}, temps={'t1': 22.4, 't2': 23.0, 'avg': 22.7}, gps=fix
```

### GPS Jitter Filtered
```
INFO - Posting telemetry: temp=22.7, water=74.0, delta_km=None, gps_fix=yes
DEBUG - Filtering GPS jitter: 12.5m < 30m threshold
DEBUG - GPS fix available but delta_km filtered (jitter/invalid)
INFO - Telemetry posted successfully
```

### Heater Automation Applied
```
INFO - New settings version 5 detected, applying...
INFO - Desired state: {'heater_auto': True, 'heater_on_below_c': 5.0, 'heater_off_above_c': 23.0, 'heater_force': 'auto'}
INFO - Actions: heater auto ON (temp 4.5°C < 5.0°C)
INFO - Successfully applied and acknowledged version 5
INFO - Relay states after change: {'heater': 'on'}
```

### Heater Hold Time Blocking
```
INFO - Actions: heater auto OFF (temp 24.0°C > 23.0°C) (blocked: 180s hold time)
```

---

## Deployment

### Pull Latest Code
```bash
cd /home/pi/Smartify-kombi
git pull origin feature/remote-sync
```

### Restart Service
```bash
sudo systemctl restart smartify-remote-sync
```

### Verify
```bash
tail -f /var/log/smartify/remote_sync.log
```

**Look for**:
- ✅ "Telemetry posted successfully"
- ✅ "Device state updated"
- ✅ `State: relays=..., temps=..., gps=...`
- ✅ GPS movement logged when driving
- ✅ GPS jitter filtered when stationary

---

## Summary

✅ **All 6 tasks completed**:
1. ✅ Enriched telemetry upload (no GPS in table)
2. ✅ Enriched device_state.current_state (GPS admin-only)
3. ✅ Relay status upload + control
4. ✅ Remote desired_state polling + application
5. ✅ Heater automation with hold time
6. ✅ km_year with GPS safety filters

✅ **Privacy enforced**:
- GPS coordinates NEVER in telemetry table
- GPS coordinates ONLY in device_state (admin-only)
- Public view shows only km_year (aggregated)

✅ **Safety implemented**:
- GPS jitter filter (< 30m)
- Speed sanity check (< 180 km/h)
- Time delta validation (<= 10 minutes)
- Heater hold time (5 minutes)
- Threshold validation (hysteresis)

✅ **Backward compatible**:
- No telemetry schema changes
- Existing dashboards work
- Local mode unchanged

**Ready for production deployment!** 🚀

