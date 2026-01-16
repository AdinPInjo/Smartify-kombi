# Smartify Supabase Payloads Documentation

This document describes the data payloads exchanged between the Raspberry Pi device and Supabase for telemetry, settings, and state synchronization.

---

## Overview

The Smartify remote sync system uses three main data flows:

1. **Telemetry Upload** (Pi → Supabase): Device sends sensor readings
2. **Desired State Retrieval** (Supabase → Pi): Device fetches configuration settings
3. **State Acknowledgment** (Pi → Supabase): Device reports applied configuration and current state

---

## 1. Telemetry Payload

### POST `/ingestTelemetry`

**Purpose**: Upload sensor readings and GPS data to Supabase.

**Frequency**: Every 60 seconds (configurable)

**Headers**:
```
Authorization: Bearer <SUPABASE_ANON_KEY>
apikey: <SUPABASE_ANON_KEY>
x-device-token: <DEVICE_TOKEN>
Content-Type: application/json
```

**Request Body**:
```json
{
  "temperature_c": 22.7,
  "water_percent": 74.0,
  "delta_km": 0.125,
  "gps_lat": 43.8563,
  "gps_lon": 18.4131,
  "ts": "2026-01-16T14:30:00Z"
}
```

**Field Descriptions**:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `temperature_c` | float | No | Average temperature in Celsius from all sensors |
| `water_percent` | float | No | Water tank level percentage (0-100) |
| `delta_km` | float | No | Distance traveled since last reading (kilometers) |
| `gps_lat` | float | No | GPS latitude (WGS84) |
| `gps_lon` | float | No | GPS longitude (WGS84) |
| `ts` | string | No | ISO 8601 timestamp (defaults to server time if omitted) |

**Notes**:
- All fields are optional (allows partial data upload)
- `temperature_c` is the average of all temperature sensors
- Individual sensor readings are stored in `device_state.current_state` (see below)
- `delta_km` is calculated using Haversine formula from last GPS position

**Response**:
```json
{
  "success": true,
  "message": "Telemetry ingested"
}
```

**Database Impact**:
- Inserts row into `public.telemetry` table
- Updates `public.device_state.last_seen` to current timestamp

---

## 2. Desired State Schema

### GET `/getDesiredState`

**Purpose**: Retrieve configuration settings that the device should apply.

**Frequency**: Every 15 seconds (configurable)

**Headers**:
```
Authorization: Bearer <SUPABASE_ANON_KEY>
apikey: <SUPABASE_ANON_KEY>
x-device-token: <DEVICE_TOKEN>
```

**Response Body**:
```json
{
  "version": 5,
  "desired_state": {
    "heater_auto": true,
    "heater_on_below_c": 5.0,
    "heater_off_above_c": 23.0,
    "heater_force": "auto",
    "pump_force": "off",
    "lights_mode": "dim",
    "gps_enabled": true
  }
}
```

**Field Descriptions**:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `version` | int | 1 | Configuration version number (auto-incremented on changes) |
| `desired_state` | object | {} | Configuration object (see below) |

### Desired State Fields

| Field | Type | Values | Description |
|-------|------|--------|-------------|
| `heater_auto` | boolean | true/false | Enable automatic heater control based on temperature |
| `heater_on_below_c` | float | default: 5.0 | Turn heater ON when temperature drops below this value |
| `heater_off_above_c` | float | default: 23.0 | Turn heater OFF when temperature rises above this value |
| `heater_force` | string | "on", "off", "auto" | Override automatic control: force heater on/off or use auto mode |
| `pump_force` | string | "on", "off" | Force water pump on or off |
| `lights_mode` | string | "off", "dim", "on" | Set lighting mode |
| `gps_enabled` | boolean | true/false | Enable/disable GPS logging (optional, for future use) |

**Heater Control Logic**:

1. **Force Mode** (`heater_force`):
   - `"on"`: Heater always on (ignores temperature)
   - `"off"`: Heater always off (ignores temperature)
   - `"auto"`: Use automatic control (requires `heater_auto: true`)

2. **Auto Mode** (when `heater_force: "auto"` and `heater_auto: true`):
   - If `temperature_c < heater_on_below_c` → Turn heater ON
   - If `temperature_c > heater_off_above_c` → Turn heater OFF
   - Otherwise → Keep current state (hysteresis)

**Example Scenarios**:

**Scenario 1: Automatic Winter Heating**
```json
{
  "heater_auto": true,
  "heater_on_below_c": 5.0,
  "heater_off_above_c": 23.0,
  "heater_force": "auto"
}
```
→ Heater turns on below 5°C, off above 23°C

**Scenario 2: Force Heater Off (Summer)**
```json
{
  "heater_force": "off"
}
```
→ Heater stays off regardless of temperature

**Scenario 3: Force Heater On (Testing)**
```json
{
  "heater_force": "on"
}
```
→ Heater stays on regardless of temperature

**Database Source**:
- Read from `public.device_settings` table
- `version` auto-increments on UPDATE via trigger

---

## 3. Current State Schema

### POST `/ackState`

**Purpose**: Acknowledge applied configuration and report comprehensive device state.

**Frequency**: 
- After applying new `desired_state` (version change)
- After every telemetry post (to keep state fresh)

**Headers**:
```
Authorization: Bearer <SUPABASE_ANON_KEY>
apikey: <SUPABASE_ANON_KEY>
x-device-token: <DEVICE_TOKEN>
Content-Type: application/json
```

**Request Body**:
```json
{
  "applied_version": 5,
  "current_state": {
    "relays": {
      "heater": "on",
      "pump": "off",
      "lights": "dim"
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
    "uptime_s": 123456,
    "actions_taken": [
      "heater auto ON (temp 4.5°C < 5.0°C)"
    ]
  }
}
```

**Field Descriptions**:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `applied_version` | int | Yes | Version number of configuration that was applied |
| `current_state` | object | Yes | Comprehensive device state snapshot (see below) |

### Current State Fields

| Field | Type | Description |
|-------|------|-------------|
| `relays` | object | Current state of all relays (key: relay name, value: "on"/"off") |
| `temps` | object | Individual temperature sensor readings |
| `temps.t1` | float | Temperature sensor 1 (Celsius) |
| `temps.t2` | float | Temperature sensor 2 (Celsius) |
| `temps.avg` | float | Average temperature (Celsius) |
| `water_percent` | float | Current water level percentage (0-100) |
| `gps` | object | Current GPS coordinates (if available) |
| `gps.lat` | float | Latitude |
| `gps.lon` | float | Longitude |
| `uptime_s` | int | System uptime in seconds |
| `actions_taken` | array | List of actions performed when applying settings (optional) |

**Response**:
```json
{
  "success": true,
  "message": "State acknowledged"
}
```

**Database Impact**:
- Updates `public.device_state.applied_version` to the acknowledged version
- Updates `public.device_state.current_state` with the full state snapshot

**Notes**:
- `applied_version` should match `device_settings.version` after successful application
- `current_state` is stored as JSONB in Supabase (flexible schema)
- `actions_taken` array provides audit trail of what changed
- This endpoint is called even when version hasn't changed (to keep state fresh)

---

## Data Flow Example

### Complete Cycle

**Step 1: Admin Updates Settings**
```sql
-- Admin changes heater settings in Supabase
UPDATE device_settings 
SET desired_state = '{"heater_auto": true, "heater_on_below_c": 5.0, "heater_force": "auto"}'
WHERE device_id = 'abc-123';
-- Trigger auto-increments version to 6
```

**Step 2: Pi Polls Desired State (15s interval)**
```http
GET /getDesiredState
Response: {"version": 6, "desired_state": {...}}
```

**Step 3: Pi Detects New Version**
```
Local applied_version: 5
Remote version: 6
→ Apply new settings
```

**Step 4: Pi Applies Settings**
```
Read temperature: 4.5°C
heater_auto: true, heater_on_below_c: 5.0
→ Turn heater ON (temp below threshold)
```

**Step 5: Pi Acknowledges**
```http
POST /ackState
Body: {
  "applied_version": 6,
  "current_state": {
    "relays": {"heater": "on"},
    "temps": {"avg": 4.5},
    "actions_taken": ["heater auto ON (temp 4.5°C < 5.0°C)"]
  }
}
```

**Step 6: Pi Posts Telemetry (60s interval)**
```http
POST /ingestTelemetry
Body: {
  "temperature_c": 4.5,
  "water_percent": 74.0,
  "gps_lat": 43.8563,
  "gps_lon": 18.4131
}
```

**Step 7: Pi Updates State Snapshot**
```http
POST /ackState
Body: {
  "applied_version": 6,
  "current_state": {
    "relays": {"heater": "on"},
    "temps": {"t1": 4.3, "t2": 4.7, "avg": 4.5},
    "water_percent": 74.0,
    "gps": {"lat": 43.8563, "lon": 18.4131},
    "uptime_s": 123456
  }
}
```

---

## Backward Compatibility

### Telemetry Table Schema

The `public.telemetry` table stores:
- `temperature_c` (real) - Average temperature
- `water_percent` (real) - Water level
- `delta_km` (real) - Distance traveled
- `gps_lat`, `gps_lon` (double precision) - GPS coordinates

**Individual sensor readings** are NOT stored in the telemetry table to avoid schema changes. Instead, they are stored in `device_state.current_state` as JSONB.

### Why This Approach?

✅ **No breaking changes** to existing telemetry table
✅ **Flexible schema** for future sensor additions (JSONB)
✅ **Backward compatible** with existing dashboards
✅ **Richer data** available in `device_state` for advanced features

---

## Local Mode vs HTTP Mode

### Local Mode (File-Based)

**Telemetry**: Appends to `/var/log/smartify/telemetry_outbox.jsonl`
```jsonl
{"ts": "2026-01-16T14:30:00Z", "temperature_c": 22.7, "water_percent": 74.0}
```

**Desired State**: Reads from `/etc/smartify/desired_state.json`
```json
{"version": 1, "desired_state": {}}
```

**Ack State**: Writes to `/var/log/smartify/ack_state.json`
```json
{
  "applied_version": 1,
  "current_state": {...},
  "acknowledged_at": "2026-01-16T14:30:00Z"
}
```

### HTTP Mode (Supabase)

Uses Edge Functions as documented above with proper authentication headers.

---

## Security Notes

- **Device Token**: Treat like a password, never commit to git
- **Anon Key**: Safe to use on devices (RLS enforces permissions)
- **Service Role Key**: NEVER use on devices (only in Edge Functions)
- **Token Hashing**: Device tokens are SHA-256 hashed in database

---

## Troubleshooting

### Telemetry Not Appearing

**Check**:
1. `tail -f /var/log/smartify/remote_sync.log` - Look for "Telemetry posted successfully"
2. HTTP status codes in logs (401 = auth error, 404 = wrong URL)
3. Supabase: `SELECT * FROM telemetry ORDER BY ts DESC LIMIT 10;`

### Settings Not Applied

**Check**:
1. Logs show "New settings version X detected"
2. `actions_taken` in logs shows what was done
3. Supabase: `SELECT * FROM device_state;` - Check `applied_version` matches `device_settings.version`

### Relay States Not Updating

**Check**:
1. Local API accessible: `curl http://127.0.0.1:8000/api/relays`
2. Logs show relay state changes
3. `current_state.relays` in `device_state` table

---

## Summary

| Endpoint | Direction | Frequency | Purpose |
|----------|-----------|-----------|---------|
| `POST /ingestTelemetry` | Pi → Supabase | 60s | Upload sensor readings |
| `GET /getDesiredState` | Supabase → Pi | 15s | Fetch configuration |
| `POST /ackState` | Pi → Supabase | On change + 60s | Report applied state |

**Key Points**:
- Telemetry table stores time-series data (temperature, water, GPS, distance)
- Device state table stores latest snapshot (relays, individual temps, full state)
- Settings table stores desired configuration with auto-incrementing version
- All communication uses device token authentication
- Heater automation supports force modes and temperature thresholds

