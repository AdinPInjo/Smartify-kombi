# Changelog

All notable changes, newest first. Versions follow [semantic versioning](https://semver.org):
`0.4.1` is a fix, `0.5.0` adds features.

Each section is shown in the dashboard under Settings → Updates, so write it for
the people using the van. A release needs a `## X.Y.Z - YYYY-MM-DD` section here
(see docs/releasing.md).

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
