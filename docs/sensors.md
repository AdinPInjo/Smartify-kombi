# Sensors

Everything connected to the Pi's pins is added in the dashboard: **Sensors** tab →
**Add sensor**. A wizard asks which sensor you have, shows where each wire goes on the
Pi (with a picture of the pin header), takes one live reading to check the wiring, and
saves it. Nothing to edit in `.env`.

No sensors at all is fine: a van with only Victron devices and a diesel heater needs none.

## Which Raspberry Pi

The Raspberry Pi 3, 4, 5 and Zero 2 W all have the same 40-pin header: the same GPIO
numbers on the same physical pins. The wiring steps and the pin picture in the wizard fit
every model. On the Pi 5 the pins sit on a different chip inside (RP1); Smartify finds the
right one by itself.

## Diagnose and logs

Every sensor on the Sensors page has a **Diagnose** button: how many reads worked in the
last hour, the latest readings, and what to check ("SDA and SCL swapped?"). For more,
switch on **debug mode** (Settings → Troubleshooting, for 2 or 24 hours) and open **Logs**:
every reading and Bluetooth message, with a filter (e.g. `fridge`).

## The catalog

| Sensor | For | Connects to |
|---|---|---|
| DHT22 / AM2302, DHT11 | Cabin temperature and humidity | Any free GPIO |
| DS18B20 probe | Fridge, water tank, outside, battery box (temperature only) | The 1-Wire pin; several probes on one pin |
| BME280, SHT31, AHT20 | Accurate temperature and humidity (BME280: + pressure) | I2C (pins 3 and 5), next to the ADS1115 |
| GPS module | Map, trips, anti-theft, local weather | Serial (pins 8 and 10) |
| Water tank sender | Fresh water level (and battery voltage) | ADS1115 on I2C |
| Door contact (reed) | Doors, windows, lockers | Any free GPIO and ground |
| Motion sensor (PIR) | Someone moving inside | Any free GPIO |

Temperature sensors, doors and motion start working right away. A GPS or water sender
starts after Smartify restarts (the page offers a **Restart now** button).

## DS18B20: switching on 1-Wire

The probes need the Pi's 1-Wire bus, switched on once. The wizard shows the exact
command, for example for GPIO 22:

```bash
echo "dtoverlay=w1-gpio,gpiopin=22" | sudo tee -a /boot/firmware/config.txt && sudo reboot
```

Wire all probes in parallel (red 3.3 V, black ground, yellow data) with **one** 4.7 kΩ
resistor between data and 3.3 V. Each probe has its own id; warm one in your hand to see
which one it is.

## Doors and motion

Door contacts use the Pi's built-in pull-up: one wire to the GPIO, the other to ground.
Alerts for opened doors and motion are **off by default** (doors open all day while you're
in the van). Switch them on under Alerts → Security, optionally only at night.

## Coming from an older version

On the first start of 0.9.0, Smartify carries over what was in `backend/.env`
(`SMARTIFY_DHT22_SENSORS`, the GPS) and the water sender if it ever delivered a reading.
After that, the Sensors tab is the only place for sensors; `.env` is not changed, and the
old sensor lines there are ignored.
