# Changelog

All notable changes, newest first. Versions follow [semantic versioning](https://semver.org):
`0.4.1` is a fix, `0.5.0` adds features.

Each section is shown in the dashboard under Settings → Updates, so write it for
the people using the van. A release needs a `## X.Y.Z - YYYY-MM-DD` section here
(see docs/releasing.md).

## 0.10.0 - 2026-11-04

### Added
- Diagnose for every sensor (Sensors tab): how many reads worked in the last hour, the latest
  readings live, and plain-language hints about the wiring ("SDA and SCL swapped?").
- Debug mode (Settings → Troubleshooting): logs every sensor reading and Bluetooth message
  for 2 or 24 hours, then switches itself off.
- A Logs page with a live readout and a filter; in the side menu while debug mode is on.

### Changed
- Door contacts and motion sensors work on the Raspberry Pi 5 too.
- The README now explains what Smartify does before how it's built.

## 0.9.0 - 2026-11-04

### Added
- A Sensors tab: add sensors from a catalog with a wizard that shows where each wire goes
  on the Pi (with a picture of the pin header), tests the sensor live and saves it. No more
  editing `.env`.
- New sensor types: DS18B20 temperature probes (fridge, tank, outside; several on one pin),
  BME280 / SHT31 / AHT20 over I2C, DHT11, door contacts and motion sensors.
- Alerts when a door opens or motion is seen (off by default, optionally only at night).
- A van without any sensors works too: only Victron and a diesel heater is fine.

### Note
- Your existing sensors (DHT22s, GPS, water tank) are carried over from `.env`
  automatically. After the update, Smartify installs the drivers for the new I2C sensors
  by itself.

## 0.8.0 - 2026-11-04

### Added
- Step-by-step guides for adding Victron devices and a diesel heater: one step at a time,
  written for first-timers, with help when something doesn't work.
- Settings → Look: Dark, Daylight (light) or Auto (follows your phone), and colorful cards:
  water blue, battery green, solar yellow, heater flame-red and more.
- A weather card on the overview: now and the next days, where the van is.
- The diesel heater card has its own little flame: asleep when off, flickering while it
  ignites, burning while heating, cool blue while cooling down.
- A tablet panel button at the top right of the overview.

### Changed
- Scenes are at the top of the Switches page ("Switches & scenes").
- Water level calibration moved from Settings to the Climate page, under the tank.
- Settings → More is tidier: Alerts, Victron devices and the tablet panel have their own places.

## 0.7.0 - 2026-11-04

### Added
- Diesel heater over Bluetooth, without its app: Climate → Diesel heater. Find it nearby,
  enter its PIN, then switch it on and off and set a temperature or power level. Live status:
  heating phase, temperatures, voltage and fault codes. Works with Vevor, BYD, Hcalory,
  Sunster, HeaterCC and other heaters that use apps like AirHeaterBLE.
- The heater in scenes ("Warm up": heater on), on the overview and the tablet panel, and
  from the remote dashboard.
- Alerts for heater faults; a carbon monoxide alarm from the heater is sent right away.

### Fixed
- Releasing two versions at once could mark the older one as the newest, so devices didn't
  see the newer update.

### Note
- Off always lets the heater cool down by itself. Don't switch a diesel heater's power with
  a relay.

## 0.6.0 - 2026-11-04

### Added
- Scenes: one tap switches several relays, e.g. "Night" (heater on its rules, fan off) or
  "Leaving" (everything off). Make up to 8 under Switches → Scenes; they appear as big
  buttons on the tablet panel and as an overview card, and work from the remote dashboard.
- The tablet panel can be arranged like the overview: tap the grid icon, drag cards, pick
  widths and heights. The tablet keeps its own layout.

### Changed
- The tablet panel has a clear Exit button at the top.

## 0.5.1 - 2026-11-04

### Added
- A "Support the project ♥" link in Settings and at the end of this changelog, for anyone
  who would like to buy the maker a coffee on Ko-fi. No pop-ups, no reminders.

## 0.5.0 - 2026-11-04

### Added
- Your own overview: tap the grid icon (or "Customize overview") to drag cards around and
  give each one a width (⅓, ½, ⅔ or full) and a height (1 or 2 rows), like widgets on a
  tablet. Gaps fill themselves. Each phone or tablet keeps its own layout.
- The version is shown bottom-left in the menu; tap it for this changelog
  (also in Settings → What's new).

### Changed
- Settings → Updates explains what to do when updates aren't available yet, instead of
  showing an error.
- The overview's charging card links to the Victron setup when no devices are added yet.

## 0.4.0 - 2026-11-03

### Added
- Updates from the dashboard, on the van and on the remote dashboard: Settings → Updates
  shows what is new and installs it with one tap. Choose "Off", "Tell me" (a phone
  notification) or "Automatic" (at night, while the van is parked).
- Going back: every version since 0.4.0 can be installed again from the version list,
  and your settings and data stay.
- Safe updates: the download is checked against its checksum, your data is backed up
  first, and a version that doesn't start is undone automatically.

### Note
- Coming from 0.3.x, update the van once in the terminal:
  `cd ~/smartify-kombi && sudo ./deploy/update.sh`. After that, updates come from the dashboard.
  The remote dashboard is updated once by uploading `installer.php` again.

## 0.3.1 - 2026-11-03

### Fixed
- Remote dashboard: the map showed "Access blocked" from OpenStreetMap. The site no longer
  hides its address from the map tile server, which OpenStreetMap requires.

## 0.3.0 - 2026-11-03

### Added
- Remote dashboard for your own web hosting, installed like WordPress: upload
  `installer.php` (or the zip), follow the setup guide, and connect the van with one tap.
- Van side: Settings → Remote dashboard, to connect with a code. No `.env` and no restart needed.
- First-run setup screen to create the dashboard login (no password in the terminal).

## 0.2.0 - 2026-11-03

### Added
- Phone notifications through ntfy or Telegram, with a setup guide in the Alerts tab.
- Alerts: battery, charging, cold and heat, water, sensor faults, relay cut-offs, the van
  moving while parked (anti-theft), frost forecast, and energy forecast.
- Travel log with stops and nights on the map.
- Victron devices added from the dashboard over Bluetooth.
- More rule options: time windows, water level, speed. Rules button on every switch.
