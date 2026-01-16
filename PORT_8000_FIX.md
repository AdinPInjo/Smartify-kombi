# ✅ Port 8000 Fix - Complete

## Problem

The Smartify API runs on port **8000** (uvicorn), but the remote sync adapters were configured to call port **5000**, causing:
- "Connection refused" errors
- All telemetry values (`temperature_c`, `water_percent`, `gps`) = `None`

## Solution

Updated all remote sync configuration and documentation to use port **8000**.

---

## Files Changed

### 1. Systemd Service Configuration

**File:** `smartify/deploy/smartify-remote-sync.service`

**Change:**
```diff
- Environment="SMARTIFY_LOCAL_API_BASE=http://127.0.0.1:5000"
+ Environment="SMARTIFY_LOCAL_API_BASE=http://127.0.0.1:8000"
```

### 2. Adapter Default Port

**File:** `smartify/remote_sync/adapters.py`

**Change:**
```diff
- LOCAL_API_BASE = os.getenv("SMARTIFY_LOCAL_API_BASE", "http://127.0.0.1:5000")
+ LOCAL_API_BASE = os.getenv("SMARTIFY_LOCAL_API_BASE", "http://127.0.0.1:8000")
```

### 3. Installer Auto-Restart

**File:** `smartify/deploy/install_remote_sync.sh`

**Change:** Added logic to automatically restart the service if already running:
```bash
if sudo systemctl is-active --quiet smartify-remote-sync; then
    echo "🔄 Service is already running. Restarting to apply changes..."
    sudo systemctl restart smartify-remote-sync
    # ... show status ...
else
    # Ask if user wants to start
    # ...
fi
```

### 4. Documentation Updates

All documentation updated with port **8000**:
- `REMOTE_SYNC_INTEGRATION_FIXES.md`
- `REMOTE_SYNC_QUICKSTART.md`
- `REMOTE_SYNC_LOCAL_MODE.md`
- `smartify/remote_sync/README.md`

Added API verification commands:
```bash
curl -s http://127.0.0.1:8000/api/water/level/live
```

---

## Apply the Fix on Raspberry Pi

### Step 1: Pull Latest Changes

```bash
cd /home/pi/Smartify-kombi
git pull origin feature/remote-sync
```

**Expected output:**
```
Updating 0227b22..XXXXXXX
Fast-forward
 smartify/deploy/smartify-remote-sync.service    | 2 +-
 smartify/remote_sync/adapters.py                | 2 +-
 smartify/deploy/install_remote_sync.sh          | 24 +++++++++++++++++++-----
 REMOTE_SYNC_*.md                                 | XX ++++++++++++++---------
 X files changed, XX insertions(+), XX deletions(-)
```

### Step 2: Reinstall Service (Applies Port Fix)

```bash
cd /home/pi/Smartify-kombi
bash smartify/deploy/install_remote_sync.sh
```

**What happens:**
1. Detects service is already running
2. Automatically restarts with new port configuration
3. Reloads systemd daemon
4. Shows service status

**Expected output:**
```
🚐 Smartify Remote Sync Installation
=====================================

...
⚙️  Installing systemd service...
   ✓ Service installed for user: pi

🔄 Enabling service (will start on boot)...
   ✓ Service enabled

🔄 Service is already running. Restarting to apply changes...

📊 Service status:
● smartify-remote-sync.service - Smartify Remote Sync Service (Local Mode)
     Loaded: loaded (/etc/systemd/system/smartify-remote-sync.service; enabled)
     Active: active (running) since ...
     ...

✅ Service restarted!
```

---

## Verification

### 1. Check Service Environment

```bash
# View service environment (should show port 8000)
sudo systemctl show smartify-remote-sync | grep SMARTIFY_LOCAL_API_BASE
```

**Expected output:**
```
Environment=SMARTIFY_LOCAL_API_BASE=http://127.0.0.1:8000
```

### 2. Test API Endpoints

```bash
# Test that API is reachable on port 8000
curl -s http://127.0.0.1:8000/api/water/level/live | jq '.level_percent'
curl -s http://127.0.0.1:8000/api/temperature/latest | jq '.sensors[0].temperature_c'
```

**Expected:** Real values (not null or connection errors)

### 3. Check Logs for HTTP API Success

```bash
# View recent logs (should show successful API calls)
tail -f /var/log/smartify/remote_sync.log
```

**Expected log messages:**
```
INFO - Temperature from HTTP API: 22.5°C (avg of 2 sensors)
INFO - Water level from HTTP API: 68%
INFO - Posting telemetry: temp=22.5, water=68.0, delta_km=None, gps=no
INFO - Telemetry posted successfully
```

**NOT this (old error):**
```
WARNING - HTTP API request failed: HTTPConnectionPool(host='127.0.0.1', port=5000): Max retries exceeded
```

### 4. Verify Telemetry Has Real Data

```bash
# View last telemetry entry
tail -1 /var/log/smartify/telemetry_outbox.jsonl | jq
```

**Expected output (with REAL values, not null):**
```json
{
  "ts": "2026-01-16T20:45:23.456789",
  "temperature_c": 22.5,
  "water_percent": 68.0
}
```

**NOT this (old problem - all null):**
```json
{
  "ts": "2026-01-16T20:45:23.456789"
}
```

### 5. Continuous Monitoring (60 seconds)

```bash
# Watch for new telemetry entries with real data
tail -f /var/log/smartify/telemetry_outbox.jsonl | jq
```

**What to look for:**
- New entry appears every 60 seconds
- `temperature_c` and `water_percent` have real values (not null)
- Logs show "from HTTP API" or "from direct import"

---

## Quick Verification One-Liner

```bash
# Wait 60s for new telemetry, then check if temperature_c and water_percent are NOT null
sleep 65 && tail -1 /var/log/smartify/telemetry_outbox.jsonl | jq '{temperature_c, water_percent}' && echo "✅ Both values present = WORKING" || echo "❌ Values are null = BROKEN"
```

---

## Troubleshooting

### Still Getting Connection Refused

```bash
# 1. Check if main app is running
sudo systemctl status smartify-app

# 2. Verify port 8000 is listening
sudo ss -tlnp | grep :8000
# or
sudo netstat -tlnp | grep :8000

# Expected output:
# tcp   0   0 0.0.0.0:8000   0.0.0.0:*   LISTEN   12345/python

# 3. Test API manually
curl -v http://127.0.0.1:8000/api/water/level/live

# If connection refused, start the main app:
sudo systemctl start smartify-app
```

### Service Not Restarting

```bash
# Force reinstall
sudo systemctl stop smartify-remote-sync
cd /home/pi/Smartify-kombi
bash smartify/deploy/install_remote_sync.sh

# Check logs
sudo journalctl -u smartify-remote-sync -n 50
```

### Still Seeing Port 5000 in Environment

```bash
# Check installed service file
sudo cat /etc/systemd/system/smartify-remote-sync.service | grep SMARTIFY_LOCAL_API_BASE

# Should show:
# Environment="SMARTIFY_LOCAL_API_BASE=http://127.0.0.1:8000"

# If showing 5000, reinstall:
cd /home/pi/Smartify-kombi
git pull origin feature/remote-sync
bash smartify/deploy/install_remote_sync.sh
```

---

## Summary

### What Changed:
- ✅ Systemd service: Port 5000 → 8000
- ✅ Adapter default: Port 5000 → 8000
- ✅ Installer: Auto-restart if running
- ✅ All docs: Port 5000 → 8000

### How to Apply:
```bash
cd /home/pi/Smartify-kombi
git pull origin feature/remote-sync
bash smartify/deploy/install_remote_sync.sh
```

### How to Verify:
```bash
# Wait 60 seconds, then check telemetry
tail -1 /var/log/smartify/telemetry_outbox.jsonl | jq '{temperature_c, water_percent}'

# Expected: Real values, NOT null
# {
#   "temperature_c": 22.5,
#   "water_percent": 68.0
# }
```

**Fix complete! The remote sync service will now successfully read sensors via HTTP API on port 8000.** ✅

