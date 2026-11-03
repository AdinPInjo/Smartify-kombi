-- The dashboard login, created in the first-run setup. The password is stored
-- as a scrypt hash, never in plain text. Device only, never synced.
CREATE TABLE account (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    username        TEXT NOT NULL,
    password_hash   TEXT NOT NULL,
    updated_at      INTEGER NOT NULL
);
