# 🚀 Remote Sync Quick Start Guide

## Installation (One Command)

```bash
cd /home/pi/Smartify-kombi && bash smartify/deploy/install_remote_sync.sh
```

This will:
- ✅ Detect your user automatically
- ✅ Create all necessary directories
- ✅ Install service to run as YOUR user (not hardcoded)
- ✅ Enable autostart on boot
- ✅ Optionally start immediately

## Verification (Copy-Paste)

### 1. Check Service

```bash
sudo systemctl status smartify-remote-sync
```

**Expected:** `Active: active (running)`

### 2. Watch Live Logs

```bash
tail -f /var/log/smartify/remote_sync.log
```

**Expected:** Messages like:
```
INFO - Posting telemetry: temp=22.5, water=68.0, delta_km=None, gps=no
INFO - Telemetry posted successfully
```

### 3. Verify Real Data in Telemetry

```bash
tail -5 /var/log/smartify/telemetry_outbox.jsonl | jq
```

**Expected:** Real sensor values (NOT all null):
```json
{
  "ts": "2026-01-16T15:30:45.123456",
  "temperature_c": 22.5,
  "water_percent": 68.0
}
```

### 4. Check Sensor Sources

```bash
grep "from direct import\|from HTTP API" /var/log/smartify/remote_sync.log | tail -10
```

**Shows:** Whether sensors use direct imports or HTTP API fallback

### 5. Test API Endpoints (If Using HTTP Fallback)

```bash
# Temperature
curl -s http://127.0.0.1:5000/api/temperature/latest | jq '.sensors[].temperature_c'

# Water level
curl -s http://127.0.0.1:5000/api/water/level/live | jq '.level_percent'

# GPS
curl -s http://127.0.0.1:5000/api/gps/current | jq '{lat, lon, ok}'
```

## Common Issues & Fixes

### ❌ All Telemetry Values Are Null

**Cause:** Sensor reading failed (both direct import and HTTP API)

**Fix:**
```bash
# Check if main app is running
sudo systemctl status smartify-app

# Check if APIs respond
curl http://127.0.0.1:5000/api/temperature/latest
curl http://127.0.0.1:5000/api/water/level/live

# Check detailed logs
grep "Error reading\|HTTP API" /var/log/smartify/remote_sync.log | tail -20
```

### ❌ Service Running as Wrong User

**Symptom:** Permission errors in logs

**Fix:**
```bash
# Check current user
ps aux | grep "remote_sync/runner.py"

# Reinstall with correct user detection
sudo systemctl stop smartify-remote-sync
sudo rm /etc/systemd/system/smartify-remote-sync.service
sudo systemctl daemon-reload
cd /home/pi/Smartify-kombi
bash smartify/deploy/install_remote_sync.sh
```

### ❌ Connection Refused Errors

**Cause:** Main smartify app not running or wrong port

**Fix:**
```bash
# Check if app is running
sudo systemctl status smartify-app

# Check what port it's using
sudo netstat -tlnp | grep python

# If different port, update environment in service file:
sudo nano /etc/systemd/system/smartify-remote-sync.service
# Change: Environment="SMARTIFY_LOCAL_API_BASE=http://127.0.0.1:XXXX"
sudo systemctl daemon-reload
sudo systemctl restart smartify-remote-sync
```

## Daily Usage

### View Latest Telemetry

```bash
tail -1 /var/log/smartify/telemetry_outbox.jsonl | jq
```

### Update Settings

```bash
# Edit settings file (increment version!)
sudo nano /etc/smartify/desired_state.json

# Example:
{
  "version": 1,
  "desired_state": {
    "heaterEnabled": true,
    "targetTemperature": 21
  }
}

# Check if applied (within 15 seconds)
cat /var/lib/smartify/applied_version.txt
```

### Restart Service

```bash
sudo systemctl restart smartify-remote-sync
```

### View Full Logs

```bash
# Live tail
tail -f /var/log/smartify/remote_sync.log

# Recent logs
sudo journalctl -u smartify-remote-sync -n 100

# Search for errors
grep ERROR /var/log/smartify/remote_sync.log
```

## Success Indicators

✅ **Working Correctly:**
- Service status: `Active: active (running)`
- Logs show: `Telemetry posted successfully` every 60s
- Telemetry file has real temperature_c and water_percent values
- No ERROR messages in logs

❌ **Needs Attention:**
- Service status: `failed` or `inactive`
- All telemetry values are null
- Logs show: `HTTP API request failed` repeatedly
- ERROR messages about permissions or I2C

## File Locations Reference

| File | Purpose |
|------|---------|
| `/var/log/smartify/telemetry_outbox.jsonl` | All telemetry data |
| `/var/log/smartify/remote_sync.log` | Service logs |
| `/etc/smartify/desired_state.json` | Settings (edit this) |
| `/var/lib/smartify/applied_version.txt` | Current version |
| `/var/lib/smartify/last_gps.json` | GPS state |

## Next Steps

1. ✅ Install and verify service is running
2. ✅ Confirm telemetry has real data (not all null)
3. ✅ Test settings update by editing desired_state.json
4. ⏭️ Optionally implement control functions in adapters.py
5. ⏭️ Set up cloud sync when ready (HTTP mode)

**Documentation:** See `REMOTE_SYNC_INTEGRATION_FIXES.md` for detailed troubleshooting

---

**Quick Test (30 seconds):**
```bash
# Install
cd /home/pi/Smartify-kombi && bash smartify/deploy/install_remote_sync.sh

# Wait 60 seconds, then check
tail -1 /var/log/smartify/telemetry_outbox.jsonl | jq

# Should see real temperature_c and water_percent values ✅
```

