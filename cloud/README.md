# Smartify Kombi: remote dashboard

The same dashboard as on the van, reachable from anywhere, running on ordinary
shared hosting: PHP 8.0+ and MySQL/MariaDB (or SQLite). No Composer, no SSH,
no Node on the server.

## How it works

```
Raspberry Pi (van)                         Your hosting
SQLite, sensors, relays  ── HTTPS ──▶      PHP API + MySQL + dashboard
                         ◀── commands ──
```

* The **Pi starts every exchange** (every 10 s by default), so it works behind
  mobile networks and needs no open ports.
* Every minute the Pi uploads its live state and new history rows (about
  5–10 MB of mobile data per day with the defaults).
* Changes made remotely become **commands**; the Pi applies them with the same
  checks as local changes and reports the result.
  * Switching a relay is only applied if it reaches the van within 15 minutes.
    An old "heater on" never fires hours later.
  * A settings change is rejected if that setting was changed on the van in
    the meantime: the van's change wins, and the dashboard says so.
* Some things only make sense on the van and are hidden here: WiFi, water
  calibration from the live reading, adding/deleting relays, the live log,
  GPX archive downloads, notification and Victron setup, the van's login.

## Install (like WordPress)

You need web hosting with **PHP 8.0+** (almost every host has it) and, ideally,
a free **HTTPS** certificate (Let's Encrypt, one click in most panels). No SSH,
no Composer, no Node on the server.

**Option A: one file** (easiest)

1. Download `installer.php` from the project's
   [latest release](https://github.com/AdinPInjo/Smartify-kombi/releases/latest).
2. In your hosting's file manager, create an empty folder (e.g. `public_html/kombi`)
   and upload `installer.php` into it.
3. Open `https://your-domain/kombi/installer.php` and press **Download and install**.

**Option B: the zip**

1. Download `smartify-cloud.zip` from the latest release.
2. Upload it to an empty folder and unzip it there with the file manager (the
   files inside `smartify-cloud/` belong in that folder, including the hidden
   `.htaccess` files).
3. Open `https://your-domain/kombi/`.

Either way, the setup guide then:

1. **checks your hosting** (PHP, database support, folder permissions, HTTPS,
   that the private folder is protected) and explains anything to fix;
2. sets up the **database**: MySQL/MariaDB (create an empty database and user
   in your panel first; the guide explains where) or SQLite (nothing to create);
3. creates your **login** for the remote dashboard;
4. **connects your van**: with your phone on the van's WiFi, tap **Connect my
   van** and confirm on the van's dashboard. Or copy the connection code and
   paste it on the van under **Settings → Remote dashboard**. The page shows
   "Connected" as soon as the van checks in. No `.env`, no restart.

## Updating

Upload `installer.php` from the newest release again and open it: it asks for
your login, downloads the new version and keeps your settings and data
(`private/`). Or upload the new zip's files over the old ones (keep `private/`).
The database is updated automatically on the next visit.

## Reconnecting the van

In the remote dashboard: **Settings → Van connection → New connection code**,
then give the new code to the van (button or paste). The old code stops working.

The folder `private/` holds the configuration (and the SQLite file, if you chose
SQLite). Its `.htaccess` blocks web access, which the installer checks. If your
host runs nginx, ask them to deny access to `/private/`.

## Settings

Edit `private/config.php`:

| Key | Default | |
|---|---|---|
| `command_ttl_seconds` | 900 | How long a switch command waits for the van |
| `history_days` | 90 | History kept on the server |

Forgot the password? Delete `private/config.php` and open the address again to
run the setup (the data stays in the database). Then connect the van again.

### Older setup: `.env`

The van can also be connected with `SMARTIFY_CLOUD_URL` and
`SMARTIFY_CLOUD_TOKEN` in `backend/.env` (then restart). A connection made in
the van's dashboard takes precedence.

## Development

```bash
scripts/build-cloud.sh                  # builds dist/smartify-cloud/
cd dist/smartify-cloud && cp ../../cloud/dev-router.php . && php -S localhost:8080 dev-router.php
```

`dev-router.php` stands in for `.htaccess`. Releases are built by
`.github/workflows/release.yml` when a tag like `v0.3.0` is pushed: it attaches
`smartify-cloud.zip`, `installer.php` and the van's prebuilt `dashboard.tar.gz`.
