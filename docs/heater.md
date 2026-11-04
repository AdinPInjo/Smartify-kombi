# Diesel heater over Bluetooth

Smartify controls Chinese diesel heaters (Vevor, BYD, Hcalory, Sunster, HeaterCC and many
more) directly over Bluetooth, so you don't need the heater's app: on and off, target
temperature or power level, and live status with fault codes. The heater then also works
in scenes, alerts and the remote dashboard.

## Setup

1. Switch the heater's power on and **close its app on your phone** (most heaters accept
   only one Bluetooth connection at a time).
2. In the dashboard: **Climate → Diesel heater → Setup** (or open `/climate/heaters`).
3. Pick your heater from **Heaters nearby**, give it a name, and enter its PIN (the one
   from the app, usually **1234**).
4. Within a minute it shows "Connected". Tap **Show it on the overview** to add its card.

## Which heaters work

Heaters whose app is one of AirHeaterBLE, Hcalory, Sunster, HeaterCC or similar. Smartify
recognizes them by their Bluetooth name (for example "Air Heater", "BYD-…", "HC-…",
"Hcalory…") and finds out the protocol from the heater's first answer:

| Family | Typical brands |
|---|---|
| AA55 / AA66, plain or encrypted | Vevor, BYD and most "AirHeaterBLE" heaters |
| ABBA | HeaterCC |
| CBFF (V2.1 with PIN login) | Sunster |
| Hcalory MVP1 / MVP2 | Hcalory (HBU1S and others) |

If your heater shows up nearby but doesn't connect, the dashboard says why. Please open a
GitHub issue with its name and what the setup page shows, so it can be added.

## Safety

- **Never switch a diesel heater's 12 V supply with a relay.** After "off" the heater
  keeps its fan running until the burner is cold; cutting the power instead can damage
  the glow plug and leave the burner hot. Smartify always uses the heater's own off
  command ("Cooling down" in the dashboard is normal).
- Faults the heater reports (E-codes) are sent to your phone. A **carbon monoxide alarm**
  (on heaters with a CO sensor) is sent right away as urgent. Still fit a separate CO
  detector in the van.

## How it works

The byte-level protocols come from the open-source
[diesel-heater-ble](https://github.com/Spettacolo83/diesel-heater-ble) library, and the way
heaters are recognized follows the same author's
[Home Assistant integration](https://github.com/Spettacolo83/homeassistant-diesel-heater)
(both MIT). Thanks to everyone who reverse-engineered these heaters there.

Smartify keeps one Bluetooth connection per heater, asks for its status every 15 seconds
(5 for Hcalory) and reconnects by itself. Every Bluetooth call has a time limit, because
the Pi 3's radio can hang inside BlueZ.
