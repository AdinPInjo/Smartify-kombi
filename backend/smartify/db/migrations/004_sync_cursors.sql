-- Remote sync bookkeeping: how far each history table has been uploaded, and
-- the last cloud command applied (so a command is never applied twice).
CREATE TABLE sync_cursors (
    name    TEXT PRIMARY KEY,
    value   INTEGER NOT NULL
);
