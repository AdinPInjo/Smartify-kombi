# Smartify Kombi

**A Raspberry Pi brain for your camper van.** Temperatures, water tank,
battery and solar, GPS track and automatic switches, on a dashboard for your
phone, a tablet on the wall, and (optionally) from anywhere over the internet.

Built for a van travelling the Balkans, shared free with everyone who builds
their own.

## What it does

* **Climate**: DHT22 temperature/humidity sensors (inside, outside…), history, outside weather forecast for where you are.
* **Water**: tank level from an analog sender via an ADS1115, compensated for the changing battery voltage.
* **Energy**: Victron SmartShunt, SmartSolar MPPT, Orion and MultiPlus (VE.Bus Smart dongle) over Bluetooth, added from the dashboard: battery %, solar, alternator charging, inverter. Battery voltage from the ADS1115 as a fallback.
* **Switches**: relays for heater, fan, pump… On / Off / Auto, timed manual override, and rules like *"heater on below 8 °C, never below 20 % battery"*, schedules (*"heater on at 06:30 on weekdays"*), water level and driving/parked.
* **Safety first**: every relay goes off on start, stop or crash; dead sensors switch their relays off; per-relay temperature cutoff; systemd watchdog.
* **GPS**: route history with a time slider, distance per day, monthly GPX archive (Komoot, Strava, Google Earth). Stable position while parked, even with a weak signal.
* **Travel log**: every place you stayed an hour or more, with place name, nights and km between stops, filled in automatically.
* **Push notifications** to your phone (ntfy or Telegram), set up from the dashboard: battery low or heading low (forecast with the sun expected tomorrow), cold or hot inside, frost tonight, water low, a sensor stopped working, and **the van is moving** (theft). Quiet hours, and messages wait while the van is offline.
* **WiFi** from the dashboard: scan and join campsite networks.
* **Tablet panel**: a full-screen instrument cluster at `/panel`.
* **Remote dashboard** on any cheap PHP + MySQL web hosting: see and switch everything from anywhere. The van connects out, so no open ports or fixed IP are needed.
* **Works offline**: the van's dashboard runs on the Pi, no cloud account needed.

## Quick start

On a Raspberry Pi (3B or newer) with Raspberry Pi OS Lite:

```bash
git clone https://github.com/AdinPInjo/Smartify-kombi.git ~/smartify-kombi
cd ~/smartify-kombi && sudo ./deploy/install.sh
```

Full guide from an empty SD card: **[docs/install.md](docs/install.md)**

| Guide | |
|---|---|
| [Installation](docs/install.md) | SD card, install, first checks, troubleshooting |
| [Wiring](docs/wiring.md) | DHT22, ADS1115 + battery divider, GPS, relays, power |
| [Victron](docs/victron.md) | Bluetooth setup for SmartShunt, MPPT, Orion, MultiPlus |
| [Notifications](docs/notifications.md) | Alerts on your phone with ntfy or Telegram |
| [Rules](docs/rules.md) | Automatic switching, priorities, combined conditions |
| [Remote dashboard](cloud/README.md) | Install on your web hosting |

## Try it without a Pi

Every device has a simulation, so the whole system runs on a laptop:

```bash
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]" && python -m smartify      # API on :8000, simulated van

cd frontend && npm install && npm run dev            # dashboard on :5173
```

Sign in with `admin` / `changeme` (only allowed with simulated hardware).

## How it's built

```
backend/    Python 3.11+, FastAPI, SQLite. Runs on the Pi.
frontend/   React + TypeScript dashboard, served by the backend.
cloud/      PHP 8 + MySQL remote dashboard for shared hosting.
deploy/     Installer, updater, systemd service.
docs/       Guides.
```

* All settings: environment variables in `backend/.env` ([.env.example](.env.example)).
* History is stored as one averaged row per minute to spare the SD card, and
  kept 90 days; the GPS route is archived to GPX before deletion.
* Tests: `cd backend && pytest` (simulated hardware, no Pi needed).

## Hardware used in the original van

Raspberry Pi 3B · 2× DHT22 · ADS1115 with a 47k/10k battery divider ·
analog water level sender · NEO-6M GPS · 2-channel relay board (heater, fan) ·
Victron SmartShunt, SmartSolar MPPT, Orion, MultiPlus + VE.Bus Smart dongle.

## Disclaimer

Smartify is a convenience, not a safety system. Heaters, batteries and
electrical installations need their own protection: fuses, thermal cut-outs,
a BMS. Use at your own risk.
