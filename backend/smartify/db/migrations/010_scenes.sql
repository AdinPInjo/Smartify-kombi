-- Scenes: one tap switches several relays (e.g. "Night": heater auto, fan off).
CREATE TABLE scenes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    icon TEXT NOT NULL DEFAULT 'star',
    actions TEXT NOT NULL,          -- JSON: {"<relay id>": "on" | "off" | "auto"}
    position INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
