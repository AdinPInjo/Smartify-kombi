# Changelog

All notable changes, newest first. Versions follow [semantic versioning](https://semver.org):
`0.3.1` is a fix, `0.4.0` adds features.

## 0.3.1

### Fixed
- Remote dashboard: the map showed "Access blocked" from OpenStreetMap. The site no longer
  hides its address from the map tile server, which OpenStreetMap requires.

## 0.3.0

### Added
- Remote dashboard for your own web hosting, installed like WordPress: upload
  `installer.php` (or the zip), follow the setup guide, and connect the van with one tap.
- Van side: Settings → Remote dashboard, to connect with a code. No `.env` and no restart needed.
- First-run setup screen to create the dashboard login (no password in the terminal).

## 0.2.0

### Added
- Phone notifications through ntfy or Telegram, with a setup guide in the Alerts tab.
- Alerts: battery, charging, cold and heat, water, sensor faults, relay cut-offs, the van
  moving while parked (anti-theft), frost forecast, and energy forecast.
- Travel log with stops and nights on the map.
- Victron devices added from the dashboard over Bluetooth.
- More rule options: time windows, water level, speed. Rules button on every switch.
