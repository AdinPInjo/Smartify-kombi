-- Safety temperature cutoff per relay.
--
-- When set, the relay is forced off while `cutoff_sensor` reads above
-- `cutoff_max_c`, in every mode, manual included. It switches back once the
-- temperature has dropped 1 °C below the limit. Both columns NULL = no cutoff.
ALTER TABLE relays ADD COLUMN cutoff_sensor TEXT;
ALTER TABLE relays ADD COLUMN cutoff_max_c REAL CHECK (cutoff_max_c BETWEEN -40 AND 80);
