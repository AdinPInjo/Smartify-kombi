# Smartify Kombi backend

The Python service that runs on the Raspberry Pi: reads the sensors, switches
the relays, keeps the history and serves the dashboard. See the project
README one folder up.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"     # add ",pi" on the Raspberry Pi
python -m smartify          # simulated hardware unless SMARTIFY_HARDWARE=pi
pytest
```

| Package | What |
|---|---|
| `smartify/config.py` | All settings (`SMARTIFY_*` environment variables / `.env`) |
| `smartify/hardware/` | Device drivers (`pi/`) and their simulations (`mock/`) |
| `smartify/services/` | Relays, rules, sensors, water, energy, GPS, weather, WiFi, cloud sync |
| `smartify/workers/` | Background loops |
| `smartify/api/` | HTTP API used by the dashboard |
| `smartify/db/migrations/` | Database schema, one numbered SQL file per change |
