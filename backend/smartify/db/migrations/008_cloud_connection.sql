-- Remote dashboard connection made from the van's dashboard (instead of
-- SMARTIFY_CLOUD_URL / SMARTIFY_CLOUD_TOKEN in .env, which still work).
CREATE TABLE cloud_connection (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    url             TEXT NOT NULL,
    token           TEXT NOT NULL,
    connected_at    INTEGER NOT NULL
);
