-- Diesel heaters controlled over Bluetooth (Vevor, Hcalory, Sunster, ...).
-- Device only: the PIN is never sent to the remote dashboard.
CREATE TABLE heaters (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    mac         TEXT NOT NULL UNIQUE,       -- AA:BB:CC:DD:EE:FF
    pin         INTEGER NOT NULL DEFAULT 1234,
    created_at  INTEGER NOT NULL
);
