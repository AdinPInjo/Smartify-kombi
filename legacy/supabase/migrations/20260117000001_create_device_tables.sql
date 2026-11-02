-- Devices table: stores device information and token hash
CREATE TABLE devices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Telemetry table: stores sensor readings from devices
CREATE TABLE telemetry (
    id BIGSERIAL PRIMARY KEY,
    device_id UUID NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    temperature_c REAL,
    water_percent REAL,
    delta_km REAL,
    gps_lat DOUBLE PRECISION,
    gps_lon DOUBLE PRECISION
);

CREATE INDEX idx_telemetry_device_ts ON telemetry(device_id, ts DESC);
CREATE INDEX idx_telemetry_ts ON telemetry(ts DESC);

-- Device settings table: stores desired configuration
CREATE TABLE device_settings (
    device_id UUID PRIMARY KEY REFERENCES devices(id) ON DELETE CASCADE,
    version INTEGER NOT NULL DEFAULT 1,
    settings JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Device state table: stores device's current state and applied version
CREATE TABLE device_state (
    device_id UUID PRIMARY KEY REFERENCES devices(id) ON DELETE CASCADE,
    applied_version INTEGER DEFAULT 0,
    current_state JSONB DEFAULT '{}'::jsonb,
    last_seen TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Public latest view: exposes latest telemetry for public dashboard
CREATE VIEW public_latest AS
SELECT 
    t.device_id,
    d.name AS device_name,
    t.ts,
    t.temperature_c,
    t.water_percent,
    (
        SELECT COALESCE(SUM(t2.delta_km), 0)
        FROM telemetry t2
        WHERE t2.device_id = t.device_id
          AND t2.ts >= DATE_TRUNC('year', NOW())
    ) AS km_year
FROM telemetry t
INNER JOIN devices d ON t.device_id = d.id
WHERE t.ts = (
    SELECT MAX(ts)
    FROM telemetry
    WHERE device_id = t.device_id
);

-- Enable Row Level Security
ALTER TABLE devices ENABLE ROW LEVEL SECURITY;
ALTER TABLE telemetry ENABLE ROW LEVEL SECURITY;
ALTER TABLE device_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE device_state ENABLE ROW LEVEL SECURITY;

-- RLS Policies

-- Devices: Only service role can access (token_hash must never be exposed to clients)
CREATE POLICY "Service role can manage devices"
    ON devices
    FOR ALL
    USING (auth.role() = 'service_role');

-- Telemetry: Service role can insert (from Edge Functions), authenticated users can read
CREATE POLICY "Service role can insert telemetry"
    ON telemetry
    FOR INSERT
    WITH CHECK (auth.role() = 'service_role');

CREATE POLICY "Authenticated users can read telemetry"
    ON telemetry
    FOR SELECT
    USING (auth.role() = 'authenticated');

-- Device settings: Authenticated users (admins) can manage
CREATE POLICY "Authenticated users can manage device settings"
    ON device_settings
    FOR ALL
    USING (auth.role() = 'authenticated')
    WITH CHECK (auth.role() = 'authenticated');

-- Device state: Service role can update, authenticated users can read
CREATE POLICY "Service role can update device state"
    ON device_state
    FOR ALL
    USING (auth.role() = 'service_role');

CREATE POLICY "Authenticated users can read device state"
    ON device_state
    FOR SELECT
    USING (auth.role() = 'authenticated');

-- Grant SELECT on public_latest view to anon role (no RLS on views)
GRANT SELECT ON public_latest TO anon;
GRANT SELECT ON public_latest TO authenticated;

-- Comments
COMMENT ON TABLE devices IS 'Device registry with hashed authentication tokens';
COMMENT ON TABLE telemetry IS 'Telemetry data from devices';
COMMENT ON TABLE device_settings IS 'Desired configuration state for devices';
COMMENT ON TABLE device_state IS 'Current state of devices (applied config and last seen)';
COMMENT ON VIEW public_latest IS 'Latest telemetry for public dashboard (anon accessible)';

