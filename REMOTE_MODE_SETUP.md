# 🌐 Remote Mode Setup Guide

Complete guide for switching Smartify Remote Sync from local file-based mode to Supabase HTTP mode.

## Prerequisites

- Supabase project created
- Supabase CLI installed (`npm install -g supabase`)
- Device in local mode and working

## Part 1: Supabase Backend Setup

### 1. Initialize Supabase Project

```bash
cd /path/to/Smartify-kombi
supabase link --project-ref your-project-ref
```

### 2. Run Database Migrations

```bash
supabase db push
```

This creates:
- `devices` table (device registry with token hashes)
- `telemetry` table (sensor readings)
- `device_settings` table (desired configuration)
- `device_state` table (device status and applied version)
- `public_latest` view (for public dashboard)
- RLS policies (security)

### 3. Deploy Edge Functions

```bash
# Deploy all functions
supabase functions deploy ingestTelemetry
supabase functions deploy getDesiredState
supabase functions deploy ackState
```

**Note:** Edge Functions automatically have access to `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` via Supabase secrets (no manual configuration needed).

### 4. Register Device and Generate Token

**Generate a secure device token:**
```bash
# Generate 32-byte hex token
openssl rand -hex 32
# Output: e.g., "a1b2c3d4e5f6..."
```

**Hash the token (SHA-256):**
```python
import hashlib
token = "a1b2c3d4e5f6..."  # Your generated token
token_hash = hashlib.sha256(token.encode()).hexdigest()
print(token_hash)
```

**Insert device into database:**
```sql
INSERT INTO devices (name, token_hash)
VALUES ('Smartify Van #1', 'hash-from-above');
```

**Save the raw token** (not the hash) for the device configuration.

## Part 2: Device Configuration

### 1. Edit Configuration File on Pi

```bash
sudo nano /etc/smartify/remote_sync.env
```

**Update with your Supabase details:**
```bash
# Operating mode
SMARTIFY_REMOTE_MODE=http

# Local API (keep for sensor reading)
SMARTIFY_LOCAL_API_BASE=http://127.0.0.1:8000

# Supabase Edge Functions URL
SMARTIFY_REMOTE_BASE_URL=https://your-project-ref.supabase.co/functions/v1

# Device token (the RAW token, not the hash)
SMARTIFY_DEVICE_TOKEN=a1b2c3d4e5f6...
```

**Important:**
- Use the **raw token** (not the hash)
- Do **NOT** use the service_role key here
- Use the Edge Functions URL (`/functions/v1`)

### 2. Restart Service

```bash
sudo systemctl restart smartify-remote-sync
```

### 3. Verify Logs

```bash
# Watch logs for HTTP success
sudo journalctl -u smartify-remote-sync -f

# Or
tail -f /var/log/smartify/remote_sync.log
```

**Expected log messages:**
```
INFO - RemoteClient initialized in 'http' mode
INFO - HTTP mode initialized: base_url=https://your-project-ref.supabase.co/functions/v1
INFO - Telemetry posted successfully
INFO - State acknowledged: version=X
```

## Part 3: Verification

### 1. Test Edge Functions from Pi

**Test ingestTelemetry:**
```bash
curl -X POST https://your-project-ref.supabase.co/functions/v1/ingestTelemetry \
  -H "Authorization: Bearer YOUR_DEVICE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "temperature_c": 22.5,
    "water_percent": 68.0,
    "delta_km": 1.5,
    "ts": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'"
  }'
```

**Expected response:**
```json
{"success":true,"message":"Telemetry ingested"}
```

**Test getDesiredState:**
```bash
curl https://your-project-ref.supabase.co/functions/v1/getDesiredState \
  -H "Authorization: Bearer YOUR_DEVICE_TOKEN"
```

**Expected response:**
```json
{"version":0,"desired_state":{}}
```

**Test ackState:**
```bash
curl -X POST https://your-project-ref.supabase.co/functions/v1/ackState \
  -H "Authorization: Bearer YOUR_DEVICE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "applied_version": 1,
    "current_state": {"heaterEnabled": true}
  }'
```

**Expected response:**
```json
{"success":true,"message":"State acknowledged"}
```

### 2. Check Data in Supabase Dashboard

**Telemetry table:**
```sql
SELECT * FROM telemetry ORDER BY ts DESC LIMIT 10;
```

**Device state:**
```sql
SELECT * FROM device_state;
```

**Public view:**
```sql
SELECT * FROM public_latest;
```

### 3. Monitor Service Logs

```bash
# Watch for successful HTTP posts (every 60s)
grep "Telemetry posted successfully" /var/log/smartify/remote_sync.log | tail -10

# Check for errors
grep "ERROR\|WARNING" /var/log/smartify/remote_sync.log | tail -20
```

## Part 4: Admin Dashboard Updates

If using the Next.js dashboard (smartify-remote):

### 1. Update Environment Variables

```bash
# .env.local
NEXT_PUBLIC_SUPABASE_URL=https://your-project-ref.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-anon-key-here
```

### 2. Dashboard Access

- **Public dashboard (`/`)**: Uses anon key, reads `public_latest` view
- **Admin dashboard (`/admin`)**: Requires authentication, can update `device_settings`

### 3. Update Device Settings from Admin

```typescript
// From admin dashboard
const { data, error } = await supabase
  .rpc('update_device_settings', {
    p_device_id: 'device-uuid',
    p_settings: {
      heaterEnabled: true,
      targetTemperature: 21
    }
  })
```

Device will detect the new version within 15 seconds and apply.

## Troubleshooting

### ❌ "Unauthorized" Error

**Cause:** Invalid or missing device token

**Fix:**
1. Verify token in `/etc/smartify/remote_sync.env` matches the raw token (not hash)
2. Verify token hash in database matches SHA-256 of raw token
3. Check token has no extra spaces or newlines

```bash
# Test token manually
python3 <<EOF
import hashlib
token = "YOUR_RAW_TOKEN_HERE"
print("Hash:", hashlib.sha256(token.encode()).hexdigest())
EOF
```

### ❌ Connection Timeout

**Cause:** Network issues or wrong URL

**Fix:**
1. Test URL manually:
   ```bash
   curl https://your-project-ref.supabase.co/functions/v1/ingestTelemetry
   ```
2. Check firewall allows outbound HTTPS
3. Verify URL in env file (no trailing slash)

### ❌ "Failed to ingest telemetry"

**Cause:** Database error or RLS issue

**Fix:**
1. Check Supabase logs (Dashboard → Edge Functions → Logs)
2. Verify migrations ran successfully
3. Check RLS policies are correct

### ❌ Local Mode Still Writing to JSONL

**Cause:** Config not loaded or service not restarted

**Fix:**
```bash
# Check loaded environment
sudo systemctl show smartify-remote-sync | grep SMARTIFY_REMOTE_MODE

# Should show: Environment=SMARTIFY_REMOTE_MODE=http

# If not, restart:
sudo systemctl daemon-reload
sudo systemctl restart smartify-remote-sync
```

## Rollback to Local Mode

If remote mode has issues, quickly roll back:

```bash
# Edit config
sudo nano /etc/smartify/remote_sync.env
# Change: SMARTIFY_REMOTE_MODE=local

# Restart
sudo systemctl restart smartify-remote-sync
```

Telemetry will resume writing to local JSONL file.

## Security Notes

✅ **DO:**
- Keep device token secret (like a password)
- Use HTTPS for all Edge Function calls
- Rotate tokens periodically

❌ **DON'T:**
- Put device token in web app code
- Use service_role key on devices
- Commit tokens to git
- Share tokens between devices

## Performance

**Expected behavior:**
- Telemetry posted every 60 seconds
- Settings checked every 15 seconds
- Each HTTP call: 3 retries with exponential backoff
- Timeouts: 5 seconds per call

**Network usage:**
- ~1 KB per telemetry post
- ~0.5 KB per settings check
- Total: ~2-3 KB per minute

## Next Steps

1. ✅ Verify telemetry appears in Supabase
2. ✅ Test settings updates from admin dashboard
3. ✅ Monitor for 24 hours to ensure stability
4. ⏭️ Set up monitoring/alerts for device offline
5. ⏭️ Implement analytics dashboard

