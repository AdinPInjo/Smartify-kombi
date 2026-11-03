-- Settings → Updates: the owner's choice, and what the last check found.
CREATE TABLE update_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    mode TEXT NOT NULL DEFAULT 'notify' CHECK (mode IN ('off', 'notify', 'auto')),
    checked_at INTEGER,
    check_error TEXT,
    versions TEXT,           -- versions.json of the newest release
    notified_version TEXT,   -- newest version the owner was told about
    auto_version TEXT,       -- newest version an automatic update was tried for
    reported_at INTEGER      -- finish time of the last update result that was notified
);
INSERT INTO update_settings (id) VALUES (1);
