-- Energy history from the Victron devices, one averaged row per minute.
-- Columns are NULL when the corresponding device is not present or not reporting.
CREATE TABLE energy_samples (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    battery_voltage     REAL,
    battery_current     REAL,   -- A, positive = charging
    battery_soc         REAL,   -- %
    solar_power         REAL,   -- W
    solar_yield_today   REAL,   -- Wh
    dcdc_output_current REAL,   -- A
    ac_out_power        REAL,   -- W
    created_at          INTEGER NOT NULL
);
CREATE INDEX idx_energy_samples_time ON energy_samples (created_at);
