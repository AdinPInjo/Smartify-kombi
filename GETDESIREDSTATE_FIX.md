# getDesiredState Fix - Device ID in POST Request

## Problem

`getDesiredState` was being called via GET with no `device_id` parameter, causing the Supabase Edge Function to return 500 errors. The settings loop could not fetch desired state from Supabase.

---

## Solution

Updated `_get_desired_state_http()` to use **POST** with JSON body containing `device_id`:

```python
# POST request with device_id in body
payload = {"device_id": self.device_id}
response = self.session.post(url, json=payload, timeout=self.http_timeout)
```

---

## Changes Made

### 1. `smartify/remote_sync/remote_client.py`

**`_init_http_mode()`**:
- Reads `device_id` from environment (tries multiple names for compatibility):
  - `SMARTIFY_DEVICE_ID` (preferred)
  - `DEVICE_ID`
  - `REMOTE_DEVICE_ID`
- Warns if `device_id` missing (doesn't crash - allows telemetry to work)
- Logs device ID on initialization

**`_get_desired_state_http()`**:
- Changed from **GET** to **POST**
- Sends `{"device_id": "<DEVICE_ID>"}` in JSON body
- Returns `{"version": 0, "desired_state": {}}` if `device_id` missing
- Keeps existing retry/backoff logic
- Uses same `session` with auth headers (works for telemetry/ackState)

### 2. `smartify/deploy/remote_sync.env.example`

Added `SMARTIFY_DEVICE_ID` configuration:
```bash
# Device ID (UUID from devices table in Supabase)
# This identifies which device's settings to fetch from device_settings table
# Find in: Supabase Dashboard → Table Editor → devices → id column
SMARTIFY_DEVICE_ID=
```

---

## Configuration

### On the Pi

**Edit environment file**:
```bash
sudo nano /etc/smartify/remote_sync.env
```

**Add device ID**:
```bash
# Get device ID from Supabase Dashboard → Table Editor → devices
SMARTIFY_DEVICE_ID=a771910e-1234-5678-9abc-def012345678
```

**Restart service**:
```bash
sudo systemctl restart smartify-remote-sync
```

---

## Verification

### Check Logs

```bash
tail -f /var/log/smartify/remote_sync.log
```

**Expected output (within 15 seconds)**:
```
INFO - HTTP mode initialized: base_url=https://...supabase.co/functions/v1
INFO - Device ID configured: a771910e-1234-5678-9abc-def012345678
DEBUG - Got desired state from remote: version=5
```

**No more 500 errors!**

### Test Settings Application

**Update desired_state in Supabase**:
```sql
UPDATE device_settings
SET desired_state = '{"heater_auto": true, "heater_on_below_c": 5.0}'::jsonb
WHERE device_id = 'a771910e-1234-5678-9abc-def012345678';
```

**Check Pi logs** (within 15 seconds):
```
INFO - New settings version X detected, applying...
INFO - Desired state: {'heater_auto': True, 'heater_on_below_c': 5.0, ...}
INFO - Actions: heater auto ON (temp 4.5°C < 5.0°C)
```

---

## Backward Compatibility

✅ **If `SMARTIFY_DEVICE_ID` not set**:
- Logs warning: `"SMARTIFY_DEVICE_ID not set - getDesiredState will not work properly"`
- Returns empty desired state: `{"version": 0, "desired_state": {}}`
- **Telemetry and ackState continue working** (don't require device_id)
- Service doesn't crash

✅ **Local mode unchanged**:
- Reads from `/etc/smartify/desired_state.json`
- No device_id needed

---

## Error Handling

### Missing device_id
```
ERROR - SMARTIFY_DEVICE_ID not set - cannot fetch desired state
```
→ Returns `{"version": 0, "desired_state": {}}` (empty, safe)

### 404 Response
```
DEBUG - No desired state configured yet
```
→ Returns `{"version": 0, "desired_state": {}}` (empty, safe)

### 500 Response
```
WARNING - Get desired state failed (attempt 1/3): status=500, response=...
```
→ Retries with backoff (3 attempts)

---

## How to Find Device ID

### Option 1: Supabase Dashboard
1. Go to **Table Editor**
2. Select **`devices`** table
3. Copy the **`id`** column value (UUID)

### Option 2: SQL Query
```sql
SELECT id, name FROM devices;
```

### Option 3: From Device Token
If you know the device token:
```sql
SELECT id, name 
FROM devices 
WHERE token_hash = encode(digest('YOUR_RAW_TOKEN', 'sha256'), 'hex');
```

---

## Summary

✅ **Fixed**:
- `getDesiredState` now sends `device_id` in POST body
- No more 500 errors from Edge Function
- Settings loop can fetch desired state successfully

✅ **Backward Compatible**:
- If `device_id` missing: logs warning, returns empty state
- Telemetry and ackState still work
- Local mode unchanged

✅ **Easy Configuration**:
- Single env var: `SMARTIFY_DEVICE_ID`
- Clear instructions in env example
- Service restart applies changes

**Settings sync now works end-to-end!** 🎉

