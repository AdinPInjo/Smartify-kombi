# Smartify Remote Sync Verification Checklist

This checklist helps verify that the enhanced remote sync system is working correctly on the Raspberry Pi.

---

## Prerequisites

- Smartify API running on `http://127.0.0.1:8000`
- Remote sync service installed and running
- For HTTP mode: Supabase Edge Functions deployed and configured

---

## 1. Service Status Check

### Verify Service is Running

```bash
sudo systemctl status smartify-remote-sync
```

**Expected**: `active (running)`

### Check Logs

```bash
tail -f /var/log/smartify/remote_sync.log
```

**Expected output (every 60s)**:
```
INFO - Posting telemetry: temp=22.7, water=74.0, delta_km=None, gps=yes
INFO - Telemetry posted successfully
INFO - Device state updated
DEBUG - State: relays={'heater': 'on'}, temps={'t1': 22.4, 't2': 23.0, 'avg': 22.7}
```

---

## 2. Local API Connectivity

### Test Temperature Endpoint

```bash
curl -s http://127.0.0.1:8000/api/temperature/latest | jq
```

**Expected**:
```json
{
  "ts": 1737036000,
  "sensors": [
    {"sensor_index": 0, "temperature_c": 22.4, "humidity": 45.0},
    {"sensor_index": 1, "temperature_c": 23.0, "humidity": 48.0}
  ]
}
```

**Verify**: Both sensors have non-null `temperature_c` values

### Test Water Level Endpoint

```bash
curl -s http://127.0.0.1:8000/api/water/level/live | jq
```

**Expected**:
```json
{
  "level_percent": 74.0,
  "ok": true,
  "status": "ready"
}
```

**Verify**: `level_percent` is a number (not null)

### Test GPS Endpoint

```bash
curl -s http://127.0.0.1:8000/api/gps/current | jq
```

**Expected** (if GPS available):
```json
{
  "ts": 1737036000,
  "lat": 43.8563,
  "lon": 18.4131,
  "speed_kmh": 0.0,
  "ok": true
}
```

**Expected** (if GPS not available):
```json
{
  "ts": null,
  "lat": null,
  "lon": null,
  "speed_kmh": null,
  "ok": false
}
```

### Test Relays Endpoint

```bash
curl -s http://127.0.0.1:8000/api/relays | jq
```

**Expected**:
```json
{
  "relays": [
    {
      "id": "abc-123",
      "name": "heater",
      "pin": 25,
      "state": "on",
      "mode": "auto",
      "is_enabled": true
    }
  ]
}
```

**Verify**: At least one relay (heater) is present with valid state

---

## 3. Telemetry Verification

### Local Mode

**Check telemetry outbox**:
```bash
tail -5 /var/log/smartify/telemetry_outbox.jsonl | jq
```

**Expected** (recent entries):
```json
{"ts": "2026-01-16T14:30:00Z", "temperature_c": 22.7, "water_percent": 74.0, "gps_lat": 43.8563, "gps_lon": 18.4131}
```

**Verify**:
- ✅ `temperature_c` is NOT null (should be average of sensors)
- ✅ `water_percent` is NOT null (should be from water level API)
- ✅ `gps_lat` and `gps_lon` present if GPS available
- ✅ New entries appear every ~60 seconds

### HTTP Mode

**Check Supabase telemetry table**:
```sql
SELECT 
  ts,
  temperature_c,
  water_percent,
  delta_km,
  gps_lat,
  gps_lon
FROM public.telemetry
WHERE device_id = 'YOUR_DEVICE_ID'
ORDER BY ts DESC
LIMIT 10;
```

**Verify**:
- ✅ Recent entries (within last 2 minutes)
- ✅ `temperature_c` has values (not null)
- ✅ `water_percent` has values (not null)
- ✅ GPS coordinates present if GPS available

---

## 4. Device State Verification

### Local Mode

**Check ack_state file**:
```bash
cat /var/log/smartify/ack_state.json | jq
```

**Expected**:
```json
{
  "applied_version": 1,
  "current_state": {
    "relays": {
      "heater": "on"
    },
    "temps": {
      "t1": 22.4,
      "t2": 23.0,
      "avg": 22.7
    },
    "water_percent": 74.0,
    "gps": {
      "lat": 43.8563,
      "lon": 18.4131
    },
    "uptime_s": 123456
  },
  "acknowledged_at": "2026-01-16T14:30:00Z"
}
```

**Verify**:
- ✅ `relays` object present with heater state
- ✅ `temps` object has `t1`, `t2`, `avg` (individual sensor readings)
- ✅ `water_percent` is a number
- ✅ `gps` object present if GPS available
- ✅ `uptime_s` is a reasonable number

### HTTP Mode

**Check Supabase device_state table**:
```sql
SELECT 
  last_seen,
  applied_version,
  current_state
FROM public.device_state
WHERE device_id = 'YOUR_DEVICE_ID';
```

**Verify**:
- ✅ `last_seen` is recent (within last 2 minutes)
- ✅ `current_state` JSONB contains:
  - `relays` object with relay states
  - `temps` object with individual sensor readings
  - `water_percent` value
  - `gps` object (if available)
  - `uptime_s` value

**Example current_state**:
```json
{
  "relays": {"heater": "on"},
  "temps": {"t1": 22.4, "t2": 23.0, "avg": 22.7},
  "water_percent": 74.0,
  "gps": {"lat": 43.8563, "lon": 18.4131},
  "uptime_s": 123456
}
```

---

## 5. Settings Application Verification

### Test Heater Automation

**Step 1: Set desired state** (HTTP mode - via Supabase SQL Editor):
```sql
UPDATE device_settings
SET desired_state = '{
  "heater_auto": true,
  "heater_on_below_c": 5.0,
  "heater_off_above_c": 23.0,
  "heater_force": "auto"
}'::jsonb
WHERE device_id = 'YOUR_DEVICE_ID';
```

**Step 2: Watch logs**:
```bash
tail -f /var/log/smartify/remote_sync.log
```

**Expected** (within 15 seconds):
```
INFO - New settings version X detected, applying...
INFO - Desired state: {'heater_auto': True, 'heater_on_below_c': 5.0, ...}
INFO - Actions: heater auto ON (temp 4.5°C < 5.0°C)
INFO - Successfully applied and acknowledged version X
INFO - Relay states after change: {'heater': 'on'}
```

**Step 3: Verify relay state changed**:
```bash
curl -s http://127.0.0.1:8000/api/relays | jq '.relays[] | select(.name=="heater") | .state'
```

**Expected**: `"on"` or `"off"` based on current temperature vs thresholds

### Test Force Modes

**Force heater ON**:
```sql
UPDATE device_settings
SET desired_state = '{"heater_force": "on"}'::jsonb
WHERE device_id = 'YOUR_DEVICE_ID';
```

**Expected in logs**:
```
INFO - Actions: heater forced ON
```

**Force heater OFF**:
```sql
UPDATE device_settings
SET desired_state = '{"heater_force": "off"}'::jsonb
WHERE device_id = 'YOUR_DEVICE_ID';
```

**Expected in logs**:
```
INFO - Actions: heater forced OFF
```

---

## 6. GPS and Distance Tracking

### Verify GPS Data Flow

**Check if GPS coordinates appear in telemetry**:

**Local mode**:
```bash
grep -i gps /var/log/smartify/telemetry_outbox.jsonl | tail -1 | jq
```

**HTTP mode**:
```sql
SELECT gps_lat, gps_lon, delta_km
FROM public.telemetry
WHERE device_id = 'YOUR_DEVICE_ID'
  AND gps_lat IS NOT NULL
ORDER BY ts DESC
LIMIT 5;
```

**Verify**:
- ✅ GPS coordinates present when vehicle is moving
- ✅ `delta_km` calculated between readings (when GPS available)
- ✅ `delta_km` is reasonable (e.g., 0.1 to 5 km for typical intervals)

### Test Distance Calculation

**Simulate movement** (for testing):
1. Note current GPS position
2. Move vehicle ~1 km
3. Wait for next telemetry post (60s)
4. Check `delta_km` in logs or database

**Expected**: `delta_km` ≈ 1.0 (within 10% margin)

---

## 7. Individual Temperature Sensors

### Verify Both Sensors Appear

**Check current_state in device_state**:
```sql
SELECT current_state->'temps' as temps
FROM public.device_state
WHERE device_id = 'YOUR_DEVICE_ID';
```

**Expected**:
```json
{
  "t1": 22.4,
  "t2": 23.0,
  "avg": 22.7
}
```

**Verify**:
- ✅ `t1` and `t2` have different values (proves they're separate sensors)
- ✅ `avg` is approximately `(t1 + t2) / 2`
- ✅ All values are reasonable temperatures (e.g., -20 to 50°C)

---

## 8. Relay State Tracking

### Verify Relay States in current_state

**Check current_state**:
```sql
SELECT current_state->'relays' as relays
FROM public.device_state
WHERE device_id = 'YOUR_DEVICE_ID';
```

**Expected**:
```json
{
  "heater": "on"
}
```

**Verify**:
- ✅ Heater state matches actual relay API state
- ✅ State updates when relay is toggled
- ✅ State persists across telemetry posts

### Test Relay Toggle Detection

**Step 1: Toggle heater manually**:
```bash
# Get heater relay ID
RELAY_ID=$(curl -s http://127.0.0.1:8000/api/relays | jq -r '.relays[] | select(.name=="heater") | .id')

# Toggle to OFF
curl -X POST http://127.0.0.1:8000/api/relays/$RELAY_ID/state \
  -H "Content-Type: application/json" \
  -d '{"state": "off", "mode": "manual"}'
```

**Step 2: Wait for next telemetry post** (~60s)

**Step 3: Check device_state**:
```sql
SELECT current_state->'relays'->'heater' as heater_state
FROM public.device_state
WHERE device_id = 'YOUR_DEVICE_ID';
```

**Expected**: `"off"`

---

## 9. Uptime Tracking

### Verify System Uptime

**Check current_state**:
```sql
SELECT current_state->'uptime_s' as uptime_seconds
FROM public.device_state
WHERE device_id = 'YOUR_DEVICE_ID';
```

**Verify**:
- ✅ Value is a positive integer
- ✅ Value increases over time
- ✅ Value resets to low number after reboot

**Convert to human-readable**:
```bash
# Example: 123456 seconds = 1.43 days
python3 -c "print(123456 / 86400, 'days')"
```

---

## 10. Error Handling

### Test Network Failure (HTTP Mode)

**Step 1: Block network temporarily**:
```bash
# Disconnect WiFi or unplug ethernet
```

**Step 2: Watch logs**:
```bash
tail -f /var/log/smartify/remote_sync.log
```

**Expected**:
```
WARNING - Telemetry post error (attempt 1/3): ...
WARNING - Telemetry post error (attempt 2/3): ...
WARNING - Telemetry post error (attempt 3/3): ...
ERROR - Failed to post telemetry after 3 attempts
```

**Verify**:
- ✅ Service does NOT crash
- ✅ Retries with backoff
- ✅ Continues running after network restored

**Step 3: Restore network**

**Expected**:
```
INFO - Telemetry posted successfully
```

### Test API Failure (Local API Down)

**Step 1: Stop Smartify API**:
```bash
sudo systemctl stop smartify
```

**Step 2: Watch logs**:
```bash
tail -f /var/log/smartify/remote_sync.log
```

**Expected**:
```
WARNING - HTTP API request failed: Connection refused
WARNING - Posting telemetry: temp=None, water=None, delta_km=None, gps=no
```

**Verify**:
- ✅ Service does NOT crash
- ✅ Posts telemetry with null values
- ✅ Continues running

**Step 3: Restart Smartify API**:
```bash
sudo systemctl start smartify
```

**Expected**:
```
INFO - Posting telemetry: temp=22.7, water=74.0, ...
```

---

## 11. Performance Check

### CPU and Memory Usage

```bash
# Check resource usage
ps aux | grep "python.*runner.py"
```

**Expected**:
- CPU: < 5% average
- Memory: < 100 MB

### Log File Size

```bash
ls -lh /var/log/smartify/remote_sync.log
```

**Expected**: < 10 MB (logrotate should manage this)

---

## Summary Checklist

Use this quick checklist for routine verification:

- [ ] Service running: `sudo systemctl status smartify-remote-sync`
- [ ] Recent logs: `tail -20 /var/log/smartify/remote_sync.log`
- [ ] Temperature NOT null in telemetry
- [ ] Water level NOT null in telemetry
- [ ] GPS coordinates present (if GPS available)
- [ ] Individual temps (t1, t2) in current_state
- [ ] Relay states in current_state
- [ ] Uptime value in current_state
- [ ] Settings version applied correctly
- [ ] Heater automation works (if configured)
- [ ] No crash on network/API failures

---

## Troubleshooting Commands

### Quick Status

```bash
# Service status
sudo systemctl status smartify-remote-sync

# Recent logs
tail -50 /var/log/smartify/remote_sync.log

# Applied version
cat /var/lib/smartify/applied_version.txt

# Last GPS
cat /var/lib/smartify/last_gps.json | jq
```

### Restart Service

```bash
sudo systemctl restart smartify-remote-sync
```

### View Full Logs

```bash
journalctl -u smartify-remote-sync -f
```

### Test Manual Telemetry Post

```bash
# Local mode - check file
tail -1 /var/log/smartify/telemetry_outbox.jsonl | jq

# HTTP mode - test Edge Function
curl -X POST https://YOUR_PROJECT.supabase.co/functions/v1/ingestTelemetry \
  -H "Authorization: Bearer YOUR_ANON_KEY" \
  -H "apikey: YOUR_ANON_KEY" \
  -H "x-device-token: YOUR_DEVICE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"temperature_c": 22.5, "water_percent": 75}'
```

---

## Success Criteria

✅ **All checks pass** if:

1. Telemetry posts every 60s with real sensor values
2. Individual temperature sensors (t1, t2) visible in current_state
3. Relay states tracked and updated in current_state
4. GPS coordinates and delta_km calculated when available
5. Settings version increments and applies correctly
6. Heater automation responds to temperature thresholds
7. System uptime tracked
8. Service recovers gracefully from network/API failures
9. No crashes or excessive resource usage

**If any check fails**, review logs and verify:
- Local API is running on port 8000
- Environment variables are set correctly
- Network connectivity (for HTTP mode)
- Device token and Supabase keys (for HTTP mode)

