-- Add multi-temperature columns to telemetry
ALTER TABLE telemetry
  ADD COLUMN IF NOT EXISTS temp_kombi_c REAL,
  ADD COLUMN IF NOT EXISTS temp_garaza_c REAL,
  ADD COLUMN IF NOT EXISTS temp_outside_c REAL;

-- Update public_latest view to include new columns
CREATE OR REPLACE VIEW public_latest AS
SELECT 
    t.device_id,
    d.name AS device_name,
    t.ts,
    t.temperature_c,
    t.temp_kombi_c,
    t.temp_garaza_c,
    t.temp_outside_c,
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
