# Wiring

The default pins, as used by the installer's defaults. Every pin can be changed
in `backend/.env` (sensors) or in the dashboard (relays).

> **Work with the van's main battery switch off** while you connect anything to
> the 12 V system. Put a fuse on every wire that leaves a battery or bus bar.

## Overview

| Part | Connects to | Pi pin (physical) | GPIO (BCM) |
|---|---|---|---|
| DHT22 "inside" data | | 7 | GPIO 4 |
| DHT22 "outside" data | | 11 | GPIO 17 |
| DHT22 power | 3.3 V | 1 or 17 | |
| ADS1115 SDA | I2C | 3 | GPIO 2 |
| ADS1115 SCL | I2C | 5 | GPIO 3 |
| ADS1115 VDD | **3.3 V** | 1 or 17 | |
| GPS TX → | Pi RX | 10 | GPIO 15 |
| GPS RX ← | Pi TX (optional) | 8 | GPIO 14 |
| GPS VCC | 5 V (most modules) | 2 or 4 | |
| Relay IN1 (heater) | | 22 | GPIO 25 |
| Relay IN2 (fan) | | 37 | GPIO 26 |
| Relay module VCC | 5 V | 2 or 4 | |
| Ground for all of the above | GND | 6, 9, 14, 20, 25, 30, 34, 39 | |

Pins Smartify will not use for relays: GPIO 0–1 (HAT EEPROM), 2–3 (I2C),
14–15 (GPS serial) and the DHT22 pins.

```
                 3V3 (1) (2)  5V
       I2C SDA GPIO2 (3) (4)  5V
       I2C SCL GPIO3 (5) (6)  GND
  DHT22 inside GPIO4 (7) (8)  GPIO14 TX  → GPS RX (optional)
                 GND (9) (10) GPIO15 RX  ← GPS TX
 DHT22 outside GPIO17 (11) (12) GPIO18
                    …
                 GND (20) (21)
                    …
   Relay heater GPIO25 (22) …
                    …
      Relay fan GPIO26 (37) (38) GPIO20
                 GND (39) (40) GPIO21
```

## DHT22 temperature and humidity sensors

```
DHT22 (front, grille facing you)      Pi
  1 VCC  ────────────────────────────  3.3 V (pin 1)
  2 DATA ───────┬────────────────────  GPIO 4 (pin 7)   (outside sensor: GPIO 17, pin 11)
                └── 10 kΩ ── 3.3 V      pull-up; already on most 3-pin modules
  3 (not connected)
  4 GND  ────────────────────────────  GND
```

* Power from **3.3 V**, never 5 V: the data line goes straight into the Pi.
* Keep cables under about 10 m. Use twisted pair or a shielded cable for the
  outside sensor and route it away from heater and inverter cables.
* Mount the outside sensor in the shade, away from the exhaust of a diesel heater.

## ADS1115: water tank level and battery voltage

The ADS1115 converts two voltages:

* **A0**: the water level sender's output
* **A1**: the battery voltage, through a divider (47 kΩ + 10 kΩ)

Smartify divides A0 by the battery voltage ("ratio" method), so the level
stays correct while the battery voltage moves between ~12 and 14.6 V.

```
ADS1115        Pi
  VDD  ──────  3.3 V      (3.3 V, not 5 V: keeps I2C safe for the Pi)
  GND  ──────  GND
  SCL  ──────  GPIO 3 (pin 5)
  SDA  ──────  GPIO 2 (pin 3)
  ADDR ──────  GND        → address 0x48
  A0   ──────  water sender signal
  A1   ──────  battery divider (below)
```

Battery voltage divider:

```
Battery + ──[fuse 1 A]──[ 47 kΩ ]──┬──── A1
                                   │
                                [ 10 kΩ ]
                                   │
Battery − (GND) ───────────────────┴──── GND (common with the Pi)
```

At 14.6 V this gives 2.56 V at A1, safely below 3.3 V. Use 1 % resistors; if
the battery voltage in the dashboard is a little off, enter the measured
resistor values under Settings → Water level calibration → Advanced.

Water sender:

* Its output on A0 must **never exceed 3.3 V**, even at 14.6 V battery voltage.
  Measure it with a multimeter with a full and an empty tank before connecting.
  If it can go higher, add a divider like the battery one.
* Calibrate in the dashboard: fill the tank → **Tank is full**; empty it →
  **Tank is empty**. Smartify works with senders that read higher when full
  and with ones that read lower.

Check the ADS1115 after the first boot: `i2cdetect -y 1` must show `48`.

**Ground:** the ADS1115, the Pi and the battery negative must share ground.
They do if the Pi's 12 → 5 V converter is non-isolated (the usual kind) and
its input negative goes to the battery negative.

## GPS (e.g. u-blox NEO-6M / NEO-M8N)

```
GPS module     Pi
  VCC  ──────  5 V (pin 2)    check your module: most have a 3.3 V regulator on board
  GND  ──────  GND (pin 6)
  TX   ──────  GPIO 15 RX (pin 10)
  RX   ──────  GPIO 14 TX (pin 8)   optional
```

* The installer enables the serial port and disables the login console on it.
* A USB GPS works too: set `SMARTIFY_GPS_DEVICE=/dev/ttyACM0` (or `ttyUSB0`).
* Put the antenna where it sees the sky (under a plastic roof vent or the
  windscreen). The first fix can take 5–15 minutes.

## Relays

Most relay modules for Arduino/Raspberry Pi work: 5 V coil, opto-isolated
input.

```
Relay module   Pi
  VCC   ─────  5 V (pin 2 or 4)
  GND   ─────  GND
  IN1   ─────  GPIO 25 (pin 22)   heater
  IN2   ─────  GPIO 26 (pin 37)   fan
```

* Many boards switch **on when the input is LOW** (active-low). If a relay clicks
  on while the dashboard says OFF, tick **Active-low board** in that relay's
  settings.
* Board with a `JD-VCC` jumper: leave the jumper on unless you power the
  coils separately.
* Contacts: check the relay's rating (often 10 A at 30 V DC). For bigger loads
  let the module switch an automotive relay or contactor, and fuse every load.
* Diesel heaters: switch the heater's **remote/enable input** or its controller
  where the manufacturer supports it, not the main power: cutting the power
  while it runs stops the cool-down cycle and can damage the heater.
* Two relays can be powered from the Pi's 5 V pin. For more, give the relay
  board its own 5 V supply (common ground).

## Victron devices

No wiring: Smartify reads them over Bluetooth. See [victron.md](victron.md).

## Powering the Pi

* Use a 12 → 5 V buck converter rated **3 A** or more, fused (2 A) on the 12 V side.
  Cheap converters cause random reboots and corrupted SD cards.
* Feed it from a circuit that stays on (not the ignition), with a low-voltage
  disconnect or the battery's BMS protecting the battery.
* A Pi 3B with sensors uses about 2–3 W (≈ 0.2 A at 12 V, ≈ 5 Ah per day).
