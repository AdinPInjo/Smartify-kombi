# Relay Bi-Directional Sync

## Overview

Heater and relay status is now **bi-directional** between the Raspberry Pi and Supabase:

- **Remote → Pi**: Commands sent from the admin UI are applied on the device (already working)
- **Pi → Remote**: Local changes on the Pi dashboard are now reflected in the remote admin UI ✅ **NEW**

## How It Works

### Telemetry Payload Enhancement

Every telemetry post (every 60s) now includes the current relay states:

```json
{
  "temperature_c": 22.5,
  "water_percent": 74.0,
  "delta_km": 0.15,
  "gps_lat": 43.856,
  "gps_lon": 18.413,
  "relays": {
    "heater": "on",
    "pump": "off",
    "lights": "dim"
  },
  "ts": "2026-01-17T12:34:56.789Z"
}
```

### Storage in Supabase

The `relays` object is stored in `device_state.current_state` JSONB field:

```sql
-- device_state table
{
  "device_id": "a771910e-...",
  "last_seen": "2026-01-17T12:34:56.789Z",
  "current_state": {
    "relays": {
      "heater": "on",
      "pump": "off",
      "lights": "dim"
    },
    "temperature_c": 22.5,
    "water_percent": 74.0,
    "gps": {
      "lat": 43.856,
      "lon": 18.413,
      "fix": true
    }
  }
}
```

### Remote Admin UI

The admin dashboard reads `device_state.current_state.relays` to display actual device status:

- Shows **actual** relay states (not just desired commands)
- Updates within 60s of local Pi changes
- Distinguishes between commanded state and actual state

## Implementation Details

### Python Client (Raspberry Pi)

**File**: `smartify/remote_sync/runner.py`

```python
# Read relay states from local API
relay_states_raw = read_relay_states()

# Normalize to simple dict
relays = {}
for relay_name, relay_info in relay_states_raw.items():
    if isinstance(relay_info, dict):
        state = relay_info.get("state", "unknown")
    else:
        state = str(relay_info)
    relays[relay_name] = state

# Post with telemetry
client.post_telemetry(
    temperature_c=temperature_c,
    water_percent=water_percent,
    delta_km=delta_km,
    gps_lat=gps_lat,
    gps_lon=gps_lon,
    relays=relays,  # ✅ NEW
)
```

**File**: `smartify/remote_sync/remote_client.py`

```python
def post_telemetry(
    self,
    temperature_c: Optional[float] = None,
    water_percent: Optional[float] = None,
    delta_km: Optional[float] = None,
    gps_lat: Optional[float] = None,
    gps_lon: Optional[float] = None,
    relays: Optional[dict] = None,  # ✅ NEW
    ts: Optional[str] = None,
) -> bool:
    # ... posts to ingestTelemetry
```

### Edge Function (Supabase)

**File**: `supabase/functions/ingestTelemetry/index.ts`

```typescript
// Parse relays from payload
const { temperature_c, water_percent, delta_km, gps_lat, gps_lon, relays, ts } = payload

// Build current_state with relay states
const currentState: any = {}

if (relays && typeof relays === 'object') {
  currentState.relays = relays  // ✅ Store relay states
}

// Update device_state with current_state
await supabase
  .from('device_state')
  .upsert({
    device_id,
    last_seen: new Date().toISOString(),
    current_state: currentState,
  }, { onConflict: 'device_id' })
```

## Relay States Format

### Normalized Format (sent to Supabase)

Simple key-value pairs with string states:

```json
{
  "heater": "on",
  "pump": "off",
  "lights": "dim"
}
```

Possible state values:
- `"on"` - Relay is active
- `"off"` - Relay is inactive
- `"dim"` - For dimmable relays (lights)
- `"unknown"` - State could not be read

### Raw Format (from local API)

Detailed relay information from `/api/relays`:

```json
{
  "heater": {
    "state": "on",
    "mode": "auto",
    "is_enabled": true
  },
  "pump": {
    "state": "off",
    "mode": "manual",
    "is_enabled": true
  }
}
```

The runner normalizes this to the simple format before sending.

## Acceptance Test

### Test Scenario

1. **Initial State**: Heater is OFF on Pi dashboard
2. **Action**: Toggle heater ON locally via Pi web dashboard
3. **Expected**: Within 60s, remote admin UI shows heater as ON
4. **Verification**: Check `device_state.current_state.relays.heater` in Supabase

### Manual Verification Steps

#### 1. Check Local Relay State
```bash
# On Raspberry Pi
curl -s http://127.0.0.1:8000/api/relays | jq
```

Expected output:
```json
{
  "ok": true,
  "relays": [
    {
      "name": "heater",
      "state": "on",
      "mode": "auto",
      "is_enabled": true
    }
  ]
}
```

#### 2. Check Telemetry Log
```bash
# On Raspberry Pi
tail -f /var/log/smartify/remote_sync.log | grep "Posting telemetry"
```

Expected log:
```
2026-01-17 12:34:56 - INFO - Posting telemetry: temp=22.5, water=74.0, delta_km=0.15, gps_lat=43.856, gps_lon=18.413, gps_fix=yes, relays={'heater': 'on', 'pump': 'off'}
```

#### 3. Check Local Mode (JSONL)
```bash
# If in local mode
tail -1 /var/log/smartify/telemetry_outbox.jsonl | jq
```

Expected output:
```json
{
  "ts": "2026-01-17T12:34:56.789Z",
  "temperature_c": 22.5,
  "water_percent": 74.0,
  "delta_km": 0.15,
  "gps_lat": 43.856,
  "gps_lon": 18.413,
  "relays": {
    "heater": "on",
    "pump": "off"
  }
}
```

#### 4. Check Supabase Device State
```sql
-- In Supabase SQL Editor
SELECT 
  device_id,
  last_seen,
  current_state->>'relays' as relays,
  current_state->'relays'->>'heater' as heater_state
FROM device_state
WHERE device_id = 'a771910e-...';
```

Expected result:
```
| device_id  | last_seen           | relays                    | heater_state |
|------------|---------------------|---------------------------|--------------|
| a771910e...| 2026-01-17 12:34:56 | {"heater":"on","pump":"off"} | on        |
```

#### 5. Verify Remote Admin UI
- Open remote admin dashboard
- Navigate to device details page
- Check "Current State" section
- Verify heater shows as "ON"

## Troubleshooting

### Relay States Not Updating

**Symptom**: Remote admin UI shows old relay state

**Diagnosis**:
```bash
# Check if telemetry is posting
tail -f /var/log/smartify/remote_sync.log | grep "Telemetry posted successfully"

# Check relay state reading
tail -f /var/log/smartify/remote_sync.log | grep "Read relay states"
```

**Possible Causes**:
1. Relay API not responding: `curl http://127.0.0.1:8000/api/relays`
2. Telemetry posting failing: Check network, device token, Supabase URL
3. Edge Function error: Check Supabase Edge Function logs

### Relay States Always "unknown"

**Symptom**: `relays={"heater": "unknown"}`

**Cause**: Local API not returning valid state

**Fix**: Check relay API endpoint implementation

### Relay States Not in Supabase

**Symptom**: `current_state.relays` is null or missing

**Diagnosis**:
```sql
-- Check raw current_state
SELECT device_id, current_state FROM device_state;
```

**Possible Causes**:
1. Edge Function not deployed: Deploy latest `ingestTelemetry/index.ts`
2. Payload missing relays: Check telemetry log for `relays={...}`
3. JSON parsing issue: Check Edge Function logs

## Benefits

✅ **Remote visibility**: Admin can see actual device state, not just commands  
✅ **Debugging**: Detect when commands don't apply (desired vs actual mismatch)  
✅ **Real-time monitoring**: Changes reflected within 60s  
✅ **No breaking changes**: Backward compatible (relays optional)  
✅ **Admin-only**: GPS coordinates in `current_state` are admin-only (not public)

## Related Files

- `smartify/remote_sync/runner.py` - Reads relay states and posts with telemetry
- `smartify/remote_sync/remote_client.py` - HTTP client with relays parameter
- `smartify/remote_sync/adapters.py` - `read_relay_states()` function
- `supabase/functions/ingestTelemetry/index.ts` - Stores relays in device_state
- Supabase table: `device_state.current_state` (JSONB column)

## Future Enhancements

- Add relay state history (optional separate table)
- Detect and alert on desired vs actual state mismatches
- Add relay state change event log for debugging
- Support for more relay types (valves, fans, etc.)

