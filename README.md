<p align="center">
  <img src="frontend/public/logo.svg" alt="" width="96" height="96">
</p>

<h1 align="center">Smartify Kombi</h1>

<p align="center">
  <strong>The smart home for your camper van, on a Raspberry Pi.</strong><br>
  Battery, solar, diesel heater, water, temperatures and location at a glance,<br>
  and everything switchable from your phone, a tablet on the wall, or anywhere in the world.
</p>

<p align="center">
  No subscription · no cloud account · works offline · set up entirely from the dashboard
</p>

---

## What it is

Smartify Kombi turns a Raspberry Pi into the brain of your van. It reads your
Victron system, controls your Chinese diesel heater over Bluetooth, watches your water
tank and temperatures, switches your fan, pump or lights, and tells your phone when
something needs you: the battery is running low, frost is coming tonight, or the van is
moving while you're asleep.

Everything is set up in the dashboard, with step-by-step guides: no coding, no config
files. Start with what you have (only a Victron shunt and a heater is fine) and add
sensors later.

Built for a VW Kombi travelling the Balkans, and shared free with everyone who builds
their own.

## Three ways to use it

| | |
|---|---|
| **📱 In the van** | Open `http://smartify.local` on your phone over the van's WiFi. Runs entirely on the Pi, so it works in the middle of nowhere. |
| **🖥️ Tablet panel** | A full-screen instrument panel for a tablet on the wall: big numbers, big buttons, your own layout. |
| **🌍 From anywhere** | Your own remote dashboard on any cheap web hosting, installed like WordPress in two minutes. Check the battery and start the heater from home. No open ports, no fixed IP: the van connects out. |

## Features

### ⚡ Energy
- **Victron over Bluetooth**: SmartShunt / BMV, SmartSolar MPPT, Orion (charging while
  driving), MultiPlus via the VE.Bus Smart dongle. Added from the dashboard with a guide.
- Battery %, time left, solar watts and yield, alternator charging, inverter.
- **Battery forecast**: "at this rate, with tomorrow's sun, you'll be at 34 % in the morning."

### 🔥 Diesel heater
- Control **Chinese diesel heaters** over Bluetooth without their app: Vevor, BYD, Hcalory,
  Sunster, HeaterCC and others (AirHeaterBLE and similar apps).
- On/off, target temperature or power level, live phase (igniting, heating, cooling down),
  burner temperature, voltage and fault codes, plus a carbon monoxide alarm on heaters that have one.
- Always switched off properly, so the heater cools down by itself.

### 🌡️ Climate, water and sensors
- A **Sensors tab** with a catalog and a wiring wizard: temperature/humidity (DHT22,
  BME280, SHT31, AHT20), waterproof probes for the fridge or tank (DS18B20), GPS, water tank
  sender, door contacts and motion sensors. It shows which pin each wire goes to and tests
  the sensor before saving.
- History charts, the **weather forecast where the van is**, and **diagnostics** for every
  sensor ("80 % of reads fail: check the data wire").
- Water tank level that stays correct while the battery voltage changes.

### 🔌 Switches, rules and scenes
- Relays for heater, fan, pump or lights: On / Off / Auto, with a timer.
- **Rules**: "fan on above 28 °C", "heater on at 06:30 on weekdays", "pump off below 10 %
  water", "never below 20 % battery".
- **Scenes**: one tap for "Night" (heater on its rules, fan off) or "Leaving" (everything off).
- Safety first: relays go off on start, stop and crash; dead sensors switch their relays
  off; temperature cut-offs; a watchdog restarts a stuck system.

### 🗺️ Map, trips and security
- GPS route with a time slider, distance per day, monthly GPX export (Komoot, Strava).
- **Travel log**: every place you stayed, with its name, nights and kilometres in between.
- **Anti-theft**: a phone alert when the van moves after standing still, or a door opens at night.

### 🔔 Alerts on your phone
- Free push notifications through **ntfy** or **Telegram**, set up in 3 minutes from the dashboard.
- Battery low (or heading there), not charging while driving, cold or hot inside, frost
  tonight, water low, heater faults, a sensor stopped working, the van is moving.
- Quiet hours, and messages wait while the van has no internet.

### ✨ Made for everyone
- First-run setup in the browser: create your login, no terminal needed.
- **Your own overview**: drag cards, give each a width and height, like widgets on a tablet.
- **Dark, Daylight or Auto** look, with colorful cards.
- **Updates from the dashboard**, with the changelog, automatic undo if something breaks,
  and going back to any earlier version.
- WiFi from the dashboard: join the campsite network.
- Debug mode and a live log, for when something doesn't work.

## What you need

- A **Raspberry Pi 3B+, 4 or 5** (or Zero 2 W) with a microSD card and a 12 V → 5 V supply.
  They all have the same 40-pin header, so the wiring guides fit every model (tested on a 3B+).
- Whatever you want to connect. All of it is optional:
  - a Victron shunt or charger with Bluetooth;
  - a diesel heater with Bluetooth;
  - sensors, a relay board, a GPS module.
- For the remote dashboard: any web hosting with PHP 8 and MySQL (or SQLite).

The original van: Raspberry Pi 3B · 2× DHT22 · ADS1115 with the water sender and a
battery divider · NEO-6M GPS · 2-channel relay board (heater, fan) · Victron SmartShunt,
SmartSolar, Orion and MultiPlus.

## Get started

On the Pi, with Raspberry Pi OS Lite:

```bash
git clone https://github.com/AdinPInjo/Smartify-kombi.git ~/smartify-kombi
cd ~/smartify-kombi && sudo ./deploy/install.sh
```

Then open **http://smartify.local** on your phone and follow the setup: create your
login, then add what you have (Sensors, Victron devices, diesel heater, alerts).

The full guide, from an empty SD card: **[docs/install.md](docs/install.md)**.

**Remote dashboard:** download `installer.php` from the
[latest release](https://github.com/AdinPInjo/Smartify-kombi/releases/latest), upload it to
an empty folder on your website and open it. Guide: [cloud/README.md](cloud/README.md).

## Guides

| Guide | |
|---|---|
| [Installation](docs/install.md) | From an empty SD card to the first login |
| [Sensors](docs/sensors.md) | The catalog, wiring, 1-Wire probes, doors and motion |
| [Wiring](docs/wiring.md) | DHT22, ADS1115 with the battery divider, GPS, relays, power |
| [Victron](docs/victron.md) | SmartShunt, MPPT, Orion and MultiPlus over Bluetooth |
| [Diesel heater](docs/heater.md) | Vevor, Hcalory, Sunster and other heaters |
| [Notifications](docs/notifications.md) | Alerts on your phone with ntfy or Telegram |
| [Rules](docs/rules.md) | Automatic switching, priorities, combined conditions |
| [Updates](docs/updates.md) | New versions from the dashboard, going back |
| [Remote dashboard](cloud/README.md) | Your own dashboard on web hosting |

---

## Technical details

### How it fits together

```
 phone / tablet ──WiFi──▶  Raspberry Pi in the van
                           ├─ FastAPI backend (Python) + SQLite
                           ├─ React dashboard, served by the backend
                           ├─ GPIO, I2C, 1-Wire, serial: sensors and relays
                           └─ Bluetooth: Victron Instant Readout, diesel heater
                                   │
                                   │ HTTPS, every 10 s, started by the van
                                   ▼
 any browser ──────────▶  Remote dashboard on web hosting (PHP 8 + MySQL/SQLite)
```

- **The Pi is the single source of truth.** The remote dashboard mirrors its state and
  history; remote changes are commands the van checks and applies on its next sync.
- **Offline first.** Everything works without internet; alerts and sync wait until it's back.
- **Gentle on the SD card.** One averaged row per minute, 90 days kept, and the GPS route
  archived as GPX before it's deleted.

### Repository

```
backend/    Python 3.11+, FastAPI, SQLite. Hardware drivers, rules, sync, API.
frontend/   React + TypeScript (Vite, TanStack Query). The dashboard and tablet panel.
cloud/      PHP 8 remote dashboard: installer, API, self-updater.
deploy/     install.sh, the updater, systemd units.
docs/       Guides.
scripts/    Release helpers.
```

### Try it without a Pi

Every device has a simulation, so the whole van runs on a laptop:

```bash
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]" && python -m smartify      # API on :8000, simulated van

cd frontend && npm install && npm run dev            # dashboard on :5173
```

Sign in with `admin` / `changeme` (only allowed with simulated hardware).

### Development

- Tests: `cd backend && pytest`. They use simulated hardware, so no Pi is needed.
- Lint: `ruff check . && ruff format --check .` (backend), `npm run build` (frontend type check).
- Database changes are numbered SQL migrations and only ever add (so going back to an older version works).
- Releases: a `CHANGELOG.md` entry, the version number, a tag. GitHub builds the release and every
  van sees it in Settings → Updates. See [docs/releasing.md](docs/releasing.md).

### Built with

[FastAPI](https://fastapi.tiangolo.com) · [React](https://react.dev) ·
[Leaflet](https://leafletjs.com) with [OpenStreetMap](https://www.openstreetmap.org) ·
[Open-Meteo](https://open-meteo.com) weather · [victron-ble](https://github.com/keshavdv/victron-ble) ·
[diesel-heater-ble](https://github.com/Spettacolo83/diesel-heater-ble) ·
[ntfy](https://ntfy.sh) · Adafruit CircuitPython drivers.

## Support

Smartify Kombi is free and built in my spare time. If it keeps your van warm or saves you
a dead battery, you can buy me a coffee:

[![Support me on Ko-fi](https://img.shields.io/badge/Ko--fi-support%20this%20project-f0a43a?logo=kofi&logoColor=white)](https://ko-fi.com/adinpinjo)

Bug reports, ideas and photos of your van setup are just as welcome: open an issue.

## Disclaimer

Smartify is a convenience, not a safety system. Heaters, batteries and electrical
installations need their own protection: fuses, thermal cut-outs, a BMS, a carbon monoxide
detector. Use at your own risk.
