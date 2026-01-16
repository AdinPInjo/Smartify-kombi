# Deployment Guide: Richer Telemetry & Heater Automation

Quick guide to deploy the enhanced remote sync system to the Raspberry Pi.

---

## Prerequisites

- SSH access to Raspberry Pi
- Smartify API running on port 8000
- Git configured on Pi

---

## Deployment Steps

### 1. Pull Latest Code

```bash
# SSH to Pi
ssh pi@smartify-van.local

# Navigate to repo
cd /home/pi/Smartify-kombi

# Pull latest changes
git fetch origin
git checkout feature/remote-sync
git pull origin feature/remote-sync
```

**Expected output**:
```
From github.com:user/Smartify-kombi
 * branch            feature/remote-sync -> FETCH_HEAD
Updating abc1234..2a04252
Fast-forward
 smartify/remote_sync/adapters.py | 200 +++++++++++++++++++++++++++++++++++
 smartify/remote_sync/runner.py   | 50 +++++++--
 ...
```

### 2. Restart Remote Sync Service

```bash
sudo systemctl restart smartify-remote-sync
```

### 3. Verify Service Started

```bash
sudo systemctl status smartify-remote-sync
```

**Expected**: `active (running)`

### 4. Watch Logs

```bash
tail -f /var/log/smartify/remote_sync.log
```

**Expected output (within 60 seconds)**:
```
INFO - Posting telemetry: temp=22.7, water=74.0, delta_km=None, gps=yes
INFO - Telemetry posted successfully
INFO - Device state updated
DEBUG - State: relays={'heater': 'on'}, temps={'t1': 22.4, 't2': 23.0, 'avg': 22.7}
```

**✅ Success indicators**:
- `temp=` is NOT None (has a number)
- `water=` is NOT None (has a number)
- `State: relays=` shows relay states
- `temps=` shows individual sensor readings (t1, t2, avg)

---

## Quick Verification

### Check Individual Temps

**Local mode**:
```bash
cat /var/log/smartify/ack_state.json | jq '.current_state.temps'
```

**Expected**:
```json
{
  "t1": 22.4,
  "t2": 23.0,
  "avg": 22.7
}
```

### Check Relay States

**Local mode**:
```bash
cat /var/log/smartify/ack_state.json | jq '.current_state.relays'
```

**Expected**:
```json
{
  "heater": "on"
}
```

### Check Telemetry Values

**Local mode**:
```bash
tail -1 /var/log/smartify/telemetry_outbox.jsonl | jq
```

**Expected**:
```json
{
  "ts": "2026-01-16T14:30:00Z",
  "temperature_c": 22.7,
  "water_percent": 74.0,
  "gps_lat": 43.8563,
  "gps_lon": 18.4131
}
```

**✅ Verify**: `temperature_c` and `water_percent` are NOT null

---

## Test Heater Automation (Local Mode)

### 1. Edit Desired State

```bash
sudo nano /etc/smartify/desired_state.json
```

**Set**:
```json
{
  "version": 2,
  "desired_state": {
    "heater_auto": true,
    "heater_on_below_c": 25.0,
    "heater_off_above_c": 30.0,
    "heater_force": "auto"
  }
}
```

**Save and exit**: `Ctrl+X`, `Y`, `Enter`

### 2. Watch Logs

```bash
tail -f /var/log/smartify/remote_sync.log
```

**Expected (within 15 seconds)**:
```
INFO - New settings version 2 detected, applying...
INFO - Desired state: {'heater_auto': True, 'heater_on_below_c': 25.0, ...}
INFO - Applied: heater auto ON (temp 22.7°C < 25.0°C)
INFO - Successfully applied and acknowledged version 2
INFO - Relay states after change: {'heater': 'on'}
```

### 3. Verify Heater Turned On

```bash
curl -s http://127.0.0.1:8000/api/relays | jq '.relays[] | select(.name=="heater") | .state'
```

**Expected**: `"on"` (because current temp is below 25°C)

---

## Test Heater Automation (HTTP Mode)

### 1. Update Desired State in Supabase

**Via Supabase SQL Editor**:
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

### 2. Watch Pi Logs

```bash
tail -f /var/log/smartify/remote_sync.log
```

**Expected (within 15 seconds)**:
```
INFO - New settings version X detected, applying...
INFO - Desired state: {'heater_auto': True, 'heater_on_below_c': 5.0, ...}
INFO - Applied: heater auto HOLD (temp 22.7°C in range)
INFO - Successfully applied and acknowledged version X
```

### 3. Check Supabase Device State

**Via Supabase SQL Editor**:
```sql
SELECT 
  applied_version,
  current_state->'temps' as temps,
  current_state->'relays' as relays,
  current_state->'actions_taken' as actions
FROM device_state
WHERE device_id = 'YOUR_DEVICE_ID';
```

**Expected**:
- `applied_version` matches `device_settings.version`
- `temps` shows `{"t1": 22.4, "t2": 23.0, "avg": 22.7}`
- `relays` shows `{"heater": "on"}`
- `actions` shows what was done

---

## Rollback (If Needed)

### If Something Goes Wrong

**1. Stop service**:
```bash
sudo systemctl stop smartify-remote-sync
```

**2. Checkout previous version**:
```bash
cd /home/pi/Smartify-kombi
git checkout <previous-commit-hash>
```

**3. Restart service**:
```bash
sudo systemctl start smartify-remote-sync
```

**4. Check logs**:
```bash
tail -f /var/log/smartify/remote_sync.log
```

---

## Troubleshooting

### Issue: Temperature is None

**Check local API**:
```bash
curl -s http://127.0.0.1:8000/api/temperature/latest | jq
```

**If fails**: Smartify API is not running
```bash
sudo systemctl status smartify
sudo systemctl start smartify
```

### Issue: Water Level is None

**Check local API**:
```bash
curl -s http://127.0.0.1:8000/api/water/level/live | jq
```

**If fails**: Water level sensor not configured or API issue

### Issue: Relay States Not Appearing

**Check relays API**:
```bash
curl -s http://127.0.0.1:8000/api/relays | jq
```

**If fails**: Relay system not initialized
```bash
# Check Smartify API logs
sudo journalctl -u smartify -n 50
```

### Issue: Service Won't Start

**Check service logs**:
```bash
sudo journalctl -u smartify-remote-sync -n 50
```

**Common causes**:
- Python import errors (missing dependencies)
- Permission errors (log files not writable)
- Configuration errors (env vars not set)

**Fix permissions**:
```bash
sudo chown -R pi:pi /var/log/smartify
sudo chown -R pi:pi /var/lib/smartify
sudo chown -R pi:pi /etc/smartify
```

### Issue: Heater Automation Not Working

**Check desired_state**:
```bash
cat /etc/smartify/desired_state.json | jq
```

**Verify**:
- `heater_auto` is `true`
- `heater_force` is `"auto"`
- Thresholds are reasonable

**Check logs for actions**:
```bash
grep -i "heater" /var/log/smartify/remote_sync.log | tail -20
```

---

## Success Criteria

✅ **Deployment successful if**:

1. Service running: `sudo systemctl status smartify-remote-sync` shows `active (running)`
2. Logs show telemetry posts every 60s
3. Temperature is NOT None in logs
4. Water level is NOT None in logs
5. Individual temps (t1, t2) appear in current_state
6. Relay states appear in current_state
7. Heater automation responds to settings changes
8. No errors in logs

---

## Next Steps

### Enable HTTP Mode (Optional)

If you want to sync with Supabase:

**1. Edit env file**:
```bash
sudo nano /etc/smartify/remote_sync.env
```

**2. Set**:
```bash
SMARTIFY_REMOTE_MODE=http
SMARTIFY_REMOTE_BASE_URL=https://YOUR_PROJECT.supabase.co/functions/v1
SMARTIFY_DEVICE_TOKEN=your-device-token-here
SMARTIFY_SUPABASE_ANON_KEY=your-anon-key-here
```

**3. Restart**:
```bash
sudo systemctl restart smartify-remote-sync
```

**4. Verify**:
```bash
tail -f /var/log/smartify/remote_sync.log
# Look for: "Telemetry posted successfully to remote"
```

---

## Documentation

- **`SMARTIFY_SUPABASE_PAYLOADS.md`** - Complete payload documentation
- **`VERIFICATION_CHECKLIST.md`** - Detailed verification procedures
- **`RICHER_TELEMETRY_SUMMARY.md`** - Implementation summary

---

## Support

**If issues persist**:
1. Check all logs: `tail -100 /var/log/smartify/remote_sync.log`
2. Check service status: `sudo systemctl status smartify-remote-sync`
3. Check API status: `sudo systemctl status smartify`
4. Review documentation: `VERIFICATION_CHECKLIST.md`
5. Test APIs manually: `curl http://127.0.0.1:8000/api/temperature/latest`

**For HTTP mode issues**:
1. Verify Supabase Edge Functions deployed
2. Verify device token in Supabase `devices` table
3. Test manually: See `REMOTE_MODE_SETUP_DASHBOARD_ONLY.md`

