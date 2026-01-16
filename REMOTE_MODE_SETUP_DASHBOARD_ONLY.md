# 🌐 Remote Mode Setup (Dashboard Only - No CLI)

Complete guide for enabling Supabase HTTP mode on Raspberry Pi using **only the Supabase Dashboard** (no CLI tools required).

---

## Prerequisites

- Supabase project created (Project ref: `zihcfiaekaiflstqxxgc`)
- Edge Functions already deployed:
  - `ingestTelemetry`
  - `getDesiredState`
  - `ackState`
- Database tables created:
  - `devices`
  - `telemetry`
  - `device_settings`
  - `device_state`
- Raspberry Pi running in local mode and working

---

## Part 1: Get Supabase Credentials

### 1. Find Your Supabase Anon Key

1. Go to Supabase Dashboard: https://supabase.com/dashboard
2. Select your project: `zihcfiaekaiflstqxxgc`
3. Navigate to: **Settings** → **API**
4. Under **Project API keys**, find: **`anon` `public`**
5. Click the **copy icon** to copy the key
6. **Save this key** - you'll need it for the Pi configuration

**Example format:**
```
eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6...
```

**Important:** 
- ✅ Use the **anon/public** key (safe for devices)
- ❌ **NEVER** use the **service_role** key on devices (security risk)

### 2. Note Your Edge Functions URL

Your Edge Functions are available at:
```
https://zihcfiaekaiflstqxxgc.supabase.co/functions/v1
```

---

## Part 2: Register Device in Supabase

### 1. Generate Device Token on Pi

SSH into your Raspberry Pi and run:

```bash
# Generate a secure random token (32 bytes = 64 hex characters)
openssl rand -hex 32
```

**Example output:**
```
a1b2c3d4e5f6789012345678901234567890abcdefabcdefabcdefabcdefabcd
```

**Save this token** - you'll need it for:
1. Inserting the hash into Supabase
2. Configuring the Pi

### 2. Hash the Token

On the Pi, hash the token with SHA-256:

```bash
# Replace YOUR_TOKEN with the token from step 1
python3 <<EOF
import hashlib
token = "a1b2c3d4e5f6789012345678901234567890abcdefabcdefabcdefabcdefabcd"  # Your token here
token_hash = hashlib.sha256(token.encode()).hexdigest()
print("Token Hash:", token_hash)
EOF
```

**Example output:**
```
Token Hash: 9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08
```

**Copy the hash** - you'll insert this into Supabase.

### 3. Insert Device into Database

1. Go to Supabase Dashboard
2. Navigate to: **SQL Editor** (left sidebar)
3. Click: **New Query**
4. Paste this SQL (replace with your values):

```sql
INSERT INTO devices (name, token_hash)
VALUES (
  'Smartify Van #1',  -- Device name (change as needed)
  '9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08'  -- Your token hash
);
```

5. Click **Run** (or press F5)
6. Verify success: You should see "Success. No rows returned"

**Check device was created:**
```sql
SELECT id, name, created_at FROM devices;
```

You should see your device listed.

---

## Part 3: Configure Raspberry Pi

### 1. Edit Configuration File

SSH into your Raspberry Pi and edit the config file:

```bash
sudo nano /etc/smartify/remote_sync.env
```

### 2. Update Configuration

**Set these values** (replace with your actual credentials):

```bash
# Operating mode - CHANGE TO HTTP
SMARTIFY_REMOTE_MODE=http

# Local API (keep for sensor reading)
SMARTIFY_LOCAL_API_BASE=http://127.0.0.1:8000

# Supabase Edge Functions URL
SMARTIFY_REMOTE_BASE_URL=https://zihcfiaekaiflstqxxgc.supabase.co/functions/v1

# Supabase anon/public key (from Part 1, Step 1)
SMARTIFY_SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6...

# Device token - RAW TOKEN, not the hash (from Part 2, Step 1)
SMARTIFY_DEVICE_TOKEN=a1b2c3d4e5f6789012345678901234567890abcdefabcdefabcdefabcdefabcd
```

**Important:**
- Use the **RAW token** for `SMARTIFY_DEVICE_TOKEN` (not the hash)
- Use the **anon/public key** for `SMARTIFY_SUPABASE_ANON_KEY`
- Make sure there are **no extra spaces** or quotes around values

### 3. Save and Exit

- Press `Ctrl+X`
- Press `Y` to confirm
- Press `Enter` to save

### 4. Restart Service

```bash
sudo systemctl restart smartify-remote-sync
```

---

## Part 4: Verification

### 1. Check Service Status

```bash
sudo systemctl status smartify-remote-sync
```

**Expected output:**
```
● smartify-remote-sync.service - Smartify Remote Sync Service
     Loaded: loaded (/etc/systemd/system/smartify-remote-sync.service; enabled)
     Active: active (running) since ...
```

### 2. Check Logs for HTTP Mode

```bash
# View recent logs
tail -50 /var/log/smartify/remote_sync.log
```

**Expected log messages:**
```
INFO - Smartify Remote Sync starting...
INFO - Mode: http
INFO - RemoteClient initialized in 'http' mode
INFO - HTTP mode initialized: base_url=https://zihcfiaekaiflstqxxgc.supabase.co/functions/v1
```

### 3. Watch for Successful Telemetry Posts

```bash
# Follow logs in real-time
tail -f /var/log/smartify/remote_sync.log
```

**Wait up to 60 seconds for telemetry post. Expected:**
```
INFO - Posting telemetry: temp=22.5, water=68.0, delta_km=None, gps=no
INFO - Telemetry posted successfully to remote
```

**NOT this (old error):**
```
WARNING - Telemetry post failed: status=401, response={"error":"Unauthorized"}
```

### 4. Verify Data in Supabase Dashboard

1. Go to Supabase Dashboard
2. Navigate to: **SQL Editor**
3. Run this query:

```sql
SELECT 
  ts,
  temperature_c,
  water_percent,
  delta_km,
  gps_lat,
  gps_lon
FROM telemetry
ORDER BY ts DESC
LIMIT 10;
```

**Expected:** You should see recent telemetry entries with real sensor data.

### 5. Check Public Dashboard View

```sql
SELECT 
  device_name,
  ts,
  temperature_c,
  water_percent,
  km_year
FROM public_latest;
```

**Expected:** Latest telemetry with calculated km_year.

---

## Troubleshooting

### ❌ "Unauthorized" Error in Logs

```
WARNING - Telemetry post failed: status=401
```

**Possible causes:**

1. **Wrong device token**
   - Check token in `/etc/smartify/remote_sync.env` matches the raw token
   - Verify hash in database matches SHA-256 of raw token
   
   **Test:**
   ```bash
   python3 <<EOF
   import hashlib
   token = "YOUR_RAW_TOKEN_FROM_ENV_FILE"
   print("Hash:", hashlib.sha256(token.encode()).hexdigest())
   EOF
   ```
   
   Compare with database:
   ```sql
   SELECT token_hash FROM devices;
   ```

2. **Wrong anon key**
   - Verify you copied the **anon/public** key (not service_role)
   - Check for extra spaces or line breaks in env file

### ❌ "Connection Refused" or Timeout

```
WARNING - Telemetry post error: Connection refused
```

**Possible causes:**

1. **Wrong URL**
   - Check: `SMARTIFY_REMOTE_BASE_URL=https://zihcfiaekaiflstqxxgc.supabase.co/functions/v1`
   - No trailing slash
   - Correct project ref

2. **Network issues**
   ```bash
   # Test network
   curl https://zihcfiaekaiflstqxxgc.supabase.co/functions/v1/ingestTelemetry
   ```

3. **Firewall blocking HTTPS**
   ```bash
   # Check firewall
   sudo iptables -L | grep HTTPS
   ```

### ❌ Still Using Local Mode

```
INFO - Mode: local
```

**Fix:**
1. Check env file has `SMARTIFY_REMOTE_MODE=http`
   ```bash
   cat /etc/smartify/remote_sync.env | grep SMARTIFY_REMOTE_MODE
   ```

2. Verify service is loading env file:
   ```bash
   sudo systemctl show smartify-remote-sync | grep SMARTIFY_REMOTE_MODE
   ```
   
   **Should show:** `Environment=SMARTIFY_REMOTE_MODE=http`

3. If still showing local, restart:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl restart smartify-remote-sync
   ```

### ❌ Missing Environment Variables

```
ERROR - SMARTIFY_SUPABASE_ANON_KEY not set for HTTP mode
```

**Fix:**
1. Edit env file and add the missing variable
   ```bash
   sudo nano /etc/smartify/remote_sync.env
   ```

2. Ensure no quotes around values:
   ```bash
   # WRONG
   SMARTIFY_SUPABASE_ANON_KEY="eyJ..."
   
   # CORRECT
   SMARTIFY_SUPABASE_ANON_KEY=eyJ...
   ```

3. Restart service

### ❌ No Data in Supabase

**Check sequence:**

1. **Service running?**
   ```bash
   sudo systemctl status smartify-remote-sync
   ```

2. **Logs show HTTP posts?**
   ```bash
   grep "Telemetry posted successfully" /var/log/smartify/remote_sync.log
   ```

3. **Any errors in logs?**
   ```bash
   grep "ERROR\|WARNING.*failed" /var/log/smartify/remote_sync.log | tail -20
   ```

4. **Edge Functions deployed?**
   - Go to Supabase Dashboard → Edge Functions
   - Verify functions are listed and deployed

5. **Database tables exist?**
   ```sql
   SELECT table_name FROM information_schema.tables 
   WHERE table_schema = 'public' 
   AND table_name IN ('devices', 'telemetry', 'device_settings', 'device_state');
   ```

---

## Rolling Back to Local Mode

If HTTP mode has issues, quickly roll back:

```bash
# 1. Edit config
sudo nano /etc/smartify/remote_sync.env
# Change: SMARTIFY_REMOTE_MODE=local

# 2. Restart
sudo systemctl restart smartify-remote-sync

# 3. Verify local mode
tail -f /var/log/smartify/telemetry_outbox.jsonl
```

Telemetry will resume writing to local JSONL file.

---

## Testing Edge Functions Manually

### Test from Pi

```bash
# Set your credentials
ANON_KEY="your-anon-key-here"
DEVICE_TOKEN="your-device-token-here"

# Test ingestTelemetry
curl -X POST https://zihcfiaekaiflstqxxgc.supabase.co/functions/v1/ingestTelemetry \
  -H "Authorization: Bearer $ANON_KEY" \
  -H "apikey: $ANON_KEY" \
  -H "x-device-token: $DEVICE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "temperature_c": 23.5,
    "water_percent": 75.0,
    "delta_km": 1.5,
    "ts": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'"
  }'
```

**Expected response:**
```json
{"success":true,"message":"Telemetry ingested"}
```

### Test getDesiredState

```bash
curl https://zihcfiaekaiflstqxxgc.supabase.co/functions/v1/getDesiredState \
  -H "Authorization: Bearer $ANON_KEY" \
  -H "apikey: $ANON_KEY" \
  -H "x-device-token: $DEVICE_TOKEN"
```

**Expected response:**
```json
{"version":0,"desired_state":{}}
```

---

## Security Notes

### ✅ Safe Practices

- Keep device token secret (like a password)
- Use anon/public key (not service_role) on devices
- Rotate device tokens periodically
- One token per device

### ❌ Unsafe Practices

- Never commit tokens to git
- Never share tokens between devices
- Never use service_role key on devices
- Never expose tokens in web apps

---

## Performance

**Expected behavior:**
- Telemetry posted every **60 seconds**
- Settings checked every **15 seconds**
- Each HTTP call: **3 retries** with backoff
- Timeout: **5 seconds** per call

**Network usage:**
- ~1 KB per telemetry post
- ~0.5 KB per settings check
- **Total: ~2-3 KB per minute**

---

## Success Checklist

After following this guide, verify:

- ✅ Service status shows `active (running)`
- ✅ Logs show `Mode: http`
- ✅ Logs show `HTTP mode initialized`
- ✅ Logs show `Telemetry posted successfully to remote` (every 60s)
- ✅ No `ERROR` or `WARNING` messages in logs
- ✅ Supabase telemetry table has recent entries
- ✅ `public_latest` view shows latest data

**If all checks pass, HTTP mode is working! 🎉**

---

## Next Steps

1. ✅ Monitor for 24 hours to ensure stability
2. ✅ Test settings updates from admin dashboard
3. ✅ Set up alerts for device offline
4. ⏭️ Configure backup device
5. ⏭️ Implement analytics dashboard

**Your Raspberry Pi is now syncing to Supabase!** 🚀

