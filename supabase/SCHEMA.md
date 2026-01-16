# Supabase Database Schema

## Overview

The Smartify remote sync backend uses Supabase with the following tables and views.

## Tables

### `devices`

Device registry with hashed authentication tokens.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| name | TEXT | Device name |
| token_hash | TEXT | SHA-256 hash of device token (UNIQUE) |
| created_at | TIMESTAMPTZ | When device was registered |

**RLS:** Only service role can access (token_hash must never be exposed)

**Device Token Setup:**
1. Generate a secure random token (e.g., `openssl rand -hex 32`)
2. Hash it with SHA-256
3. Insert into devices table with the hash
4. Give the raw token to the device (set in `SMARTIFY_DEVICE_TOKEN`)

### `telemetry`

Telemetry data from devices.

| Column | Type | Description |
|--------|------|-------------|
| id | BIGSERIAL | Primary key |
| device_id | UUID | Foreign key to devices |
| ts | TIMESTAMPTZ | Timestamp of reading |
| temperature_c | REAL | Temperature in Celsius |
| water_percent | REAL | Water level percentage |
| delta_km | REAL | Kilometers traveled since last reading |
| gps_lat | DOUBLE PRECISION | GPS latitude |
| gps_lon | DOUBLE PRECISION | GPS longitude |

**Indexes:**
- `idx_telemetry_device_ts` on (device_id, ts DESC)
- `idx_telemetry_ts` on (ts DESC)

**RLS:**
- Service role can INSERT (from Edge Functions)
- Authenticated users can SELECT

### `device_settings`

Desired configuration state for devices.

| Column | Type | Description |
|--------|------|-------------|
| device_id | UUID | Primary key, foreign key to devices |
| version | INTEGER | Configuration version number |
| settings | JSONB | Desired state (settings to apply) |
| updated_at | TIMESTAMPTZ | When settings were last updated |

**RLS:** Authenticated users (admins) can read and write

**Version Management:**
- Use `update_device_settings(device_id, settings)` function to auto-increment version
- Device polls and applies when version > applied_version

### `device_state`

Current state of devices (applied config and last seen).

| Column | Type | Description |
|--------|------|-------------|
| device_id | UUID | Primary key, foreign key to devices |
| applied_version | INTEGER | Last applied settings version |
| current_state | JSONB | Current actual state of device |
| last_seen | TIMESTAMPTZ | Last telemetry timestamp |
| updated_at | TIMESTAMPTZ | When state was last updated |

**RLS:**
- Service role can update (from Edge Functions)
- Authenticated users can read

## Views

### `public_latest`

Latest telemetry for public dashboard (anon accessible, no authentication required).

| Column | Type | Description |
|--------|------|-------------|
| device_id | UUID | Device ID |
| device_name | TEXT | Device name |
| ts | TIMESTAMPTZ | Timestamp |
| temperature_c | REAL | Latest temperature |
| water_percent | REAL | Latest water level |
| km_year | REAL | Total kilometers this year |

**Access:** Public (anon + authenticated)

## Functions

### `update_device_settings(device_id UUID, settings JSONB)`

Updates device settings and auto-increments version.

**Returns:** `device_settings` record

**Usage (from admin dashboard):**
```sql
SELECT * FROM update_device_settings(
    'device-uuid-here',
    '{"heaterEnabled": true, "targetTemperature": 21}'::jsonb
);
```

## Row Level Security (RLS)

### Security Model

1. **Devices table:**
   - ❌ Never exposed to clients (token_hash must remain secret)
   - ✅ Only service role access

2. **Telemetry:**
   - ✅ Service role inserts (via Edge Functions)
   - ✅ Authenticated admins read
   - ❌ Anon cannot read raw telemetry

3. **Public Dashboard:**
   - ✅ Anon can read `public_latest` view (safe subset of telemetry)
   - ✅ No RLS needed on views (pre-filtered data)

4. **Device Settings:**
   - ✅ Authenticated admins read/write
   - ✅ Devices fetch via Edge Function (service role)

5. **Device State:**
   - ✅ Service role updates (via Edge Functions)
   - ✅ Authenticated admins read

### Important Notes

- **NEVER** use service_role key in client code (web app or device)
- **Web app** uses anon key for public dashboard, auth for admin
- **Device** uses device token (validated in Edge Functions with service role)
- **Edge Functions** use service role key (set via Supabase secrets)

## Example Data Flow

### Device → Supabase

1. Device calls `ingestTelemetry` with `Authorization: Bearer <device_token>`
2. Edge Function validates token (hashes and checks `devices.token_hash`)
3. Edge Function inserts telemetry using service_role
4. Edge Function updates `device_state.last_seen`

### Admin → Device

1. Admin updates settings via web app (authenticated)
2. App calls `update_device_settings()` function
3. Version increments in `device_settings`
4. Device polls `getDesiredState` (sees new version)
5. Device applies settings
6. Device calls `ackState` to confirm
7. `device_state.applied_version` updated

## Migrations

Run migrations in order:
1. `20260117000001_create_device_tables.sql` - Tables and RLS
2. `20260117000002_create_helper_functions.sql` - Helper functions

```bash
supabase db push
```

## Initial Device Registration

```sql
-- Generate token hash (use external tool, e.g., Python)
-- token = "your-secure-random-token-here"
-- token_hash = sha256(token)

INSERT INTO devices (name, token_hash)
VALUES ('Smartify Van #1', 'hash-here');
```

Then set on device:
```bash
SMARTIFY_DEVICE_TOKEN=your-secure-random-token-here
```

