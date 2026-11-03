# Victron devices over Bluetooth

Smartify reads Victron's **Instant Readout** broadcasts: the live values a
device sends over Bluetooth every second or so. Reading is passive. Smartify
never connects to or changes a Victron device, and the VictronConnect app keeps
working as before.

Decoding uses [victron-ble](https://github.com/keshavdv/victron-ble).

## Supported

| Device | Shown in Smartify | Usable in rules |
|---|---|---|
| SmartShunt, BMV-712 | voltage, current, power, state of charge, time left, consumed Ah, starter or midpoint voltage, alarms | `battery_soc`, `battery_voltage`, `battery_current` |
| SmartSolar / BlueSolar MPPT with Bluetooth | solar power, charge current, yield today, charge state, errors | `solar_power`, `battery_voltage` |
| Orion-Tr Smart, Orion XS | input/output voltage, (XS: currents), charge state, off reason | |
| MultiPlus / Quattro with **VE.Bus Smart dongle** | state, AC in/out power, shore power state, battery voltage/current, SOC, alarms | `battery_soc`, `battery_voltage`, `battery_current` |

Other Instant Readout devices (Smart Battery Sense, Lithium Smart, Lynx Smart
BMS, Smart BatteryProtect, AC chargers) are decoded too and appear under
Energy → Devices.

## Setup (in the dashboard)

Go to **Energy → Add Victron devices** (or **Settings → Victron devices**).
No restart and no `.env` editing needed.

1. In **VictronConnect** on your phone, open the device, tap the **gear** (on some
   devices the **⋮** menu), then **Product info**.
2. Set **Instant readout via Bluetooth** to **Enabled**.
3. Tap **Show** next to **Instant readout details** and keep that screen open.
4. In the dashboard the device appears under **Devices nearby** within a few
   seconds. Tap **Add**, paste the **encryption key** (32 characters) and keep or
   change the suggested name (`shunt`, `solar`, `orion`, `multiplus`).
5. The key is checked against the device straight away. Its values appear on the
   Energy page within seconds.

The **name** (lowercase, no spaces) is what rules use, e.g. `battery_soc` of `shunt`.
Devices that are out of range can be added by hand with their MAC address.

### Alternative: `.env`

Devices can also be listed in `backend/.env` as `name|MAC|key`, comma separated,
followed by `sudo systemctl restart smartify`. They show up in the dashboard
marked “set in .env” and can only be removed there.

```bash
SMARTIFY_VICTRON_DEVICES=shunt|C0:3B:98:AA:BB:01|0df4d0395b7d1a876c0c33ecb9e70dcd,solar|E1:5A:24:AA:BB:02|8a14…
```

## Notes

* Keep the encryption keys private: anyone with a key can read that device's data.
  Keys added in the dashboard stay on the Pi and are never sent to the remote dashboard.
* Range: a few metres through the van's interior. Below about −90 dBm readings
  get patchy; move the Pi or the device.
* A device silent for 2 minutes (`SMARTIFY_VICTRON_STALE_SECONDS`) is shown as
  stale, and rules using it switch their relay **off**, like with a dead temperature
  sensor.
* Pi 3B: WiFi and Bluetooth share one radio. Passive scanning is light, but if
  WiFi feels slow, that's the reason.
* Bluetooth must not be disabled on the Pi (`dtoverlay=disable-bt` would turn it off).

## Ideas for rules

| Rule | Condition | Action |
|---|---|---|
| Protect the battery | `battery_soc` of `shunt` below 20 % | heater **off**, priority 900 |
| Use surplus solar | `solar_power` of `solar` above 250 W | water heater **on** |
| Fan when charging hard | `battery_current` of `shunt` above 40 A | fan **on** |

See [rules.md](rules.md).
