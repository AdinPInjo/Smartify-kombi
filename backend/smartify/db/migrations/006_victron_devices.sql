-- Victron devices added from the dashboard (devices in SMARTIFY_VICTRON_DEVICES
-- keep working too). Device only, never synced: it holds the encryption keys.
CREATE TABLE victron_devices (
    name        TEXT PRIMARY KEY,           -- used in rules, e.g. 'shunt'
    mac         TEXT NOT NULL UNIQUE,       -- AA:BB:CC:DD:EE:FF
    key         TEXT NOT NULL,              -- 32 hex characters from VictronConnect
    created_at  INTEGER NOT NULL
);
