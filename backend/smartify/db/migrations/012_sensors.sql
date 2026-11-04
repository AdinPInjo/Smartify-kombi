-- Sensors added in the dashboard (before: SMARTIFY_DHT22_SENSORS etc. in .env).
CREATE TABLE sensors (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,    -- used in rules, e.g. 'inside', 'fridge'
    kind        TEXT NOT NULL,           -- catalog type: dht22, ds18b20, bme280, gps, door, ...
    config      TEXT NOT NULL,           -- JSON: pin, address, probe id, ...
    created_at  INTEGER NOT NULL
);
-- Set once the old .env sensors were carried over (first start of 0.9.0).
CREATE TABLE sensor_setup (
    id           INTEGER PRIMARY KEY CHECK (id = 1),
    imported_at  INTEGER NOT NULL
);
