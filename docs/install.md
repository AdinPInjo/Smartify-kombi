# Installing Smartify Kombi on a Raspberry Pi

From an empty SD card to the dashboard in about 30 minutes, most of it waiting.

## What you need

| | |
|---|---|
| Raspberry Pi | 3B, 3B+, 4 or 5. A Pi 3B is enough. |
| SD card | **High Endurance**, 32 GB or more (SanDisk High Endurance, Samsung PRO Endurance). Normal cards wear out under constant writes. |
| Power | A good 12 V → 5 V converter, at least 2.5 A (3 A for a Pi 4/5), fused on the 12 V side |
| A computer | To write the SD card |
| WiFi | Your phone's hotspot or the van's router, for the installation |

Wire the sensors and relays as in [wiring.md](wiring.md) before or after the
installation; Smartify copes with missing sensors.

## 1. Write the SD card

1. Install **Raspberry Pi Imager** from <https://www.raspberrypi.com/software/>.
2. Choose your device, then **Raspberry Pi OS Lite (64-bit)**
   (Raspberry Pi OS (other) → Lite 64-bit). 64-bit works on a Pi 3B and installs faster.
3. Choose the SD card, then **Edit settings** when asked about OS customisation:
   * Hostname: `kombi` → the dashboard will be at `http://kombi.local`
   * Username and password: your choice (this is the Linux login, not the dashboard)
   * WiFi: the network the Pi should join (you can add more later from the dashboard)
   * Locale: your time zone
   * Services tab: **Enable SSH** (password authentication)
4. Write, put the card in the Pi, power it on, wait 2–3 minutes.

## 2. Log in

From a computer on the same WiFi:

```bash
ssh <your-user>@kombi.local
```

(Windows: use PowerShell or the Terminal app; the command is the same.)

## 3. Install

```bash
sudo apt-get install -y git
git clone https://github.com/AdinPInjo/Smartify-kombi.git ~/smartify-kombi
cd ~/smartify-kombi
sudo ./deploy/install.sh
```

It asks for:

* **Dashboard password**: protects the dashboard. Smartify refuses to run with the default.
* **DHT22 sensors** as `name:GPIO`: default `inside:4,outside:17`. The names show
  in the dashboard and are used in rules.
* **Relays** as `name:GPIO`: default `heater:25,fan:26`. Only used the first
  time; afterwards relays are managed in the dashboard.
* **GPS**: `true` or `false`.

Then:

```bash
sudo reboot
```

## 4. After the first boot

Open **<http://kombi.local>** on your phone (same WiFi) and sign in as `admin`.

Check, in this order:

1. **Settings → System status**: every background task has a green dot.
2. **Climate**: both temperature sensors show values after about a minute.
   "Warming up" for longer → check the DHT22 wiring.
3. **Switches**: tap **On** for each relay and listen for the click.
   * The relay clicks **on** while the dashboard says **OFF**? Your relay board is
     active-low: open the relay, tick **Active-low board**, save.
4. **Climate → Fresh water**: calibrate with a full and an empty tank
   (Settings → Water level calibration). Until then the level is approximate.
5. **Energy**: if you use Victron devices, set them up with [victron.md](victron.md).
6. Add your first rule, e.g. heater **on** when `inside` temperature is below 8 °C.
   See [rules.md](rules.md).
7. Optional: the remote dashboard on your web hosting, see
   [../cloud/README.md](../cloud/README.md).

Tablet in the van: open `http://kombi.local/panel`, then use the browser's
"Add to home screen" for a full-screen instrument panel.

## Everyday commands

```bash
journalctl -u smartify -f           # live log
sudo systemctl restart smartify     # after editing backend/.env
nano ~/smartify-kombi/backend/.env  # settings (all options: .env.example)
sudo ./deploy/update.sh             # update to the latest version
```

## Data and backups

Everything lives in `~/smartify-kombi/backend/data/`:

| | |
|---|---|
| `smartify.db` | settings and history (90 days) |
| `backups/` | a daily copy of the database (last 3) |
| `archive/gps/` | your route, one GPX file per month, kept forever |

These protect against a damaged database, not a dead SD card. Copy the
folder off the Pi now and then, or use the remote dashboard, which keeps the
history on your hosting:

```bash
scp -r <user>@kombi.local:smartify-kombi/backend/data ./kombi-backup
```

## Safety

* Every relay is switched **off** when Smartify starts, stops or crashes, and
  systemd restarts it if rule evaluation hangs.
* A rule whose sensor stops answering switches its relay **off**.
* Give heaters a **safety cutoff** (relay settings): off above a temperature,
  even when switched on by hand.
* Smartify is a convenience, not a safety device. Heaters need their own
  thermal protection and every circuit its own fuse.

## Troubleshooting

| Problem | Try |
|---|---|
| `kombi.local` not found | Use the Pi's IP address (shown in your router or hotspot). Some Android phones don't support `.local`. |
| Service not running | `journalctl -u smartify -n 50` shows why. "Refusing to start: … changeme" means no password was set in `backend/.env`. |
| DHT22 always "warming up" | Wrong GPIO in `SMARTIFY_DHT22_SENSORS`, missing pull-up resistor, or a cable longer than ~10 m. |
| Water level "not responding" | `i2cdetect -y 1` must show `48`. If empty: SDA/SCL swapped or ADS1115 not powered. |
| GPS "no device" | `ls -l /dev/serial0` must exist (reboot after installing). TX of the GPS goes to GPIO 15 (RX). |
| GPS "no fix" | First fix outdoors can take 5–15 minutes. |
| WiFi scan fails | Reboot once after installing (group permissions). |
