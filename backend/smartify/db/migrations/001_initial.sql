-- Initial schema.
--
-- Conventions:
--   * Timestamps are Unix epoch seconds (INTEGER, UTC).
--   * Booleans are INTEGER 0/1.
--   * Tables that hold user settings (relays, rules, water_level_settings)
--     carry `updated_at` and `revision`. Remote sync uses `revision` to decide
--     which side changed last, because the Pi has no real-time clock and its
--     time can be wrong until it reaches NTP or gets a GPS fix.

-- ---------------------------------------------------------------------------
-- Relays (user settings, synced)
-- ---------------------------------------------------------------------------
CREATE TABLE relays (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    label           TEXT,
    gpio_pin        INTEGER NOT NULL CHECK (gpio_pin BETWEEN 0 AND 27),
    active_low      INTEGER NOT NULL DEFAULT 0,
    enabled         INTEGER NOT NULL DEFAULT 1,
    -- 'auto' = rules decide, 'manual' = manual_state decides
    mode            TEXT NOT NULL DEFAULT 'auto' CHECK (mode IN ('auto', 'manual')),
    manual_state    TEXT CHECK (manual_state IN ('on', 'off')),
    -- When set, manual mode ends at this time and the relay returns to auto.
    manual_until    INTEGER,
    -- Protects compressors/heaters from rapid switching.
    min_on_seconds  INTEGER NOT NULL DEFAULT 0 CHECK (min_on_seconds >= 0),
    min_off_seconds INTEGER NOT NULL DEFAULT 0 CHECK (min_off_seconds >= 0),
    created_at      INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL,
    revision        INTEGER NOT NULL DEFAULT 1
);

-- Live state of each relay as applied to the hardware (device only, not synced
-- as a setting; reported to the cloud as telemetry).
CREATE TABLE relay_state (
    relay_id        TEXT PRIMARY KEY REFERENCES relays (id) ON DELETE CASCADE,
    actual_state    TEXT NOT NULL DEFAULT 'off' CHECK (actual_state IN ('on', 'off')),
    changed_at      INTEGER NOT NULL
);

CREATE TABLE relay_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    relay_id        TEXT NOT NULL REFERENCES relays (id) ON DELETE CASCADE,
    -- 'manual', 'rule', 'boot', 'remote', 'schedule'
    source          TEXT NOT NULL,
    rule_id         TEXT,
    old_state       TEXT,
    new_state       TEXT NOT NULL,
    reason          TEXT,
    created_at      INTEGER NOT NULL
);
CREATE INDEX idx_relay_events_relay_time ON relay_events (relay_id, created_at);

-- ---------------------------------------------------------------------------
-- Automation rules (user settings, synced)
-- ---------------------------------------------------------------------------
CREATE TABLE rules (
    id                TEXT PRIMARY KEY,
    relay_id          TEXT NOT NULL REFERENCES relays (id) ON DELETE CASCADE,
    name              TEXT NOT NULL,
    enabled           INTEGER NOT NULL DEFAULT 1,
    -- Lower number wins when several rules match.
    priority          INTEGER NOT NULL DEFAULT 100,
    -- JSON, validated by the rules service. Example:
    -- {"type": "band", "metric": "temperature", "sensor": "average", "on_below": 8, "off_above": 12}
    condition_json    TEXT NOT NULL,
    cooldown_seconds  INTEGER NOT NULL DEFAULT 60 CHECK (cooldown_seconds >= 0),
    last_triggered_at INTEGER,
    created_at        INTEGER NOT NULL,
    updated_at        INTEGER NOT NULL,
    revision          INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX idx_rules_relay ON rules (relay_id);

-- ---------------------------------------------------------------------------
-- Temperature / humidity
-- ---------------------------------------------------------------------------
CREATE TABLE sensor_samples (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    -- Stable sensor key, e.g. 'dht22_0'
    sensor          TEXT NOT NULL,
    temperature_c   REAL,
    humidity        REAL,
    ok              INTEGER NOT NULL,
    error           TEXT,
    created_at      INTEGER NOT NULL
);
CREATE INDEX idx_sensor_samples_sensor_time ON sensor_samples (sensor, created_at);

-- ---------------------------------------------------------------------------
-- Water level
-- ---------------------------------------------------------------------------
-- Single row (id = 1). Two calibration methods:
--   'voltage': level from the signal voltage between empty_voltage and full_voltage
--   'ratio':   level from signal / supply ratio, compensates a drifting supply
CREATE TABLE water_level_settings (
    id                  INTEGER PRIMARY KEY CHECK (id = 1),
    method              TEXT NOT NULL DEFAULT 'voltage' CHECK (method IN ('voltage', 'ratio')),
    signal_channel      INTEGER NOT NULL DEFAULT 0 CHECK (signal_channel BETWEEN 0 AND 3),
    supply_channel      INTEGER NOT NULL DEFAULT 1 CHECK (supply_channel BETWEEN 0 AND 3),
    divider_r_top       REAL NOT NULL DEFAULT 47000,
    divider_r_bottom    REAL NOT NULL DEFAULT 10000,
    empty_voltage       REAL NOT NULL DEFAULT 2.2,
    full_voltage        REAL NOT NULL DEFAULT 0.5,
    empty_ratio         REAL,
    full_ratio          REAL,
    updated_at          INTEGER NOT NULL,
    revision            INTEGER NOT NULL DEFAULT 1,
    CHECK (signal_channel <> supply_channel)
);
INSERT INTO water_level_settings (id, updated_at) VALUES (1, CAST(strftime('%s', 'now') AS INTEGER));

CREATE TABLE water_level_samples (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_voltage  REAL,
    supply_voltage  REAL,
    ratio           REAL,
    level_percent   INTEGER,
    ok              INTEGER NOT NULL,
    error           TEXT,
    created_at      INTEGER NOT NULL
);
CREATE INDEX idx_water_level_samples_time ON water_level_samples (created_at);

-- ---------------------------------------------------------------------------
-- GPS
-- ---------------------------------------------------------------------------
CREATE TABLE gps_fixes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    lat             REAL NOT NULL,
    lon             REAL NOT NULL,
    speed_kmh       REAL,
    course          REAL,
    altitude_m      REAL,
    satellites      INTEGER,
    created_at      INTEGER NOT NULL
);
CREATE INDEX idx_gps_fixes_time ON gps_fixes (created_at);

CREATE TABLE gps_distance_daily (
    day             TEXT PRIMARY KEY,   -- YYYY-MM-DD (UTC)
    distance_km     REAL NOT NULL DEFAULT 0,
    updated_at      INTEGER NOT NULL
);

-- ---------------------------------------------------------------------------
-- Outside weather (Open-Meteo, fetched for the current GPS position)
-- ---------------------------------------------------------------------------
CREATE TABLE weather_samples (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    lat             REAL NOT NULL,
    lon             REAL NOT NULL,
    temperature_c   REAL,
    humidity        REAL,
    created_at      INTEGER NOT NULL
);
CREATE INDEX idx_weather_samples_time ON weather_samples (created_at);
