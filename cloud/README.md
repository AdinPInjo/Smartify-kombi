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
  GPX archive downloads.

## Install

1. Build the package on your computer: `scripts/build-cloud.sh`
   (or download `smartify-cloud.zip` from the project's releases).
2. In your hosting panel (cPanel, Plesk…) create an empty **MySQL database**
   and a database user with full access to it.
3. Upload the contents of `smartify-cloud/` to a (sub)domain folder, e.g.
   `public_html/kombi`. Use HTTPS (Let's Encrypt is free in most panels).
4. Open `https://your-domain/kombi/install.php`, enter the database details
   and choose the dashboard login.
5. Copy the two lines it shows into `backend/.env` on the Pi and restart:

   ```
   SMARTIFY_CLOUD_URL=https://your-domain/kombi
   SMARTIFY_CLOUD_TOKEN=…
   ```

6. Optional: delete `install.php` from the server.

The folder `private/` holds the configuration (and the SQLite file, if you chose
SQLite). Its `.htaccess` blocks web access; if your host runs nginx, add a
rule denying `/private/`.

## Settings

Edit `private/config.php`:

| Key | Default | |
|---|---|---|
| `command_ttl_seconds` | 900 | How long a switch command waits for the van |
| `history_days` | 90 | History kept on the server |

Forgot the password or lost the token? Delete `private/config.php` and run
`install.php` again (the data stays in the database).

## Development

```bash
php -S localhost:8080 dev-router.php   # stands in for .htaccess
```
