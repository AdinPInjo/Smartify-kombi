# Smartify Kombi

Raspberry Pi controller for camper vans: relays (heater, fan…), temperature and
humidity, water tank level, GPS tracking, and a web dashboard.

> **Work in progress.** The project is being restructured on the
> `refactor/restructure` branch. The previous implementation lives in `legacy/`
> and is removed once everything has been ported.

## Layout

```
backend/    Python service that runs on the Pi (FastAPI + SQLite)
frontend/   Web dashboard (React)                      ← currently smartify-ui/
cloud/      Optional remote dashboard + sync (PHP + MySQL, any shared hosting)
legacy/     Old implementation, kept for reference during the port
```

## Run the backend without a Pi

The backend simulates all hardware by default, so it runs on any machine:

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m smartify          # http://localhost:8000/api/health
pytest                      # run the tests
```

On the Raspberry Pi install the hardware drivers too and switch to real hardware:

```bash
pip install -e ".[pi]"
SMARTIFY_HARDWARE=pi python -m smartify
```

All settings are environment variables; see [`.env.example`](.env.example).
