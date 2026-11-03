-- Push notifications and the automatic travel log.

-- Single row (id = 1): channels (ntfy, Telegram), alert switches and thresholds,
-- as JSON validated by smartify.services.notify. Device only, never synced:
-- it holds the Telegram bot token.
CREATE TABLE notification_settings (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    settings_json   TEXT NOT NULL,
    updated_at      INTEGER NOT NULL
);

-- Every notification, from queued to sent. Doubles as the outbox: without
-- internet a message stays 'queued' and is retried until it is delivered or
-- too old ('dropped').
CREATE TABLE notifications (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    alert           TEXT NOT NULL,          -- alert key, e.g. 'battery_low', 'test'
    title           TEXT NOT NULL,
    message         TEXT NOT NULL,
    priority        TEXT NOT NULL DEFAULT 'default'
                        CHECK (priority IN ('low', 'default', 'high', 'urgent')),
    click_url       TEXT,
    status          TEXT NOT NULL DEFAULT 'queued'
                        CHECK (status IN ('queued', 'sent', 'dropped')),
    -- JSON list of channels that already have it, so a retry never sends twice.
    delivered_json  TEXT NOT NULL DEFAULT '[]',
    attempts        INTEGER NOT NULL DEFAULT 0,
    next_attempt_at INTEGER NOT NULL,
    last_error      TEXT,
    sent_at         INTEGER,
    created_at      INTEGER NOT NULL
);
CREATE INDEX idx_notifications_queue ON notifications (status, next_attempt_at);
CREATE INDEX idx_notifications_time ON notifications (created_at);

-- Which alerts are currently active, so a restart does not send them again.
CREATE TABLE alert_state (
    key             TEXT PRIMARY KEY,       -- e.g. 'battery_low', 'sensor:inside'
    active          INTEGER NOT NULL,
    since           INTEGER NOT NULL,
    last_sent_at    INTEGER
);

-- Travel log: places where the van stood still for a while.
CREATE TABLE stops (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    lat             REAL NOT NULL,
    lon             REAL NOT NULL,
    arrived_at      INTEGER NOT NULL,
    left_at         INTEGER,                -- NULL while the van is still there
    place           TEXT,                   -- reverse geocoded (OpenStreetMap), when online
    country         TEXT,
    -- Total driven distance (gps_distance_daily) on arrival, for km between stops.
    odometer_km     REAL NOT NULL DEFAULT 0
);
CREATE INDEX idx_stops_arrived ON stops (arrived_at);
