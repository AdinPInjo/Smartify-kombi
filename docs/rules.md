# Rules

Rules switch a relay automatically while it is in **Auto** mode. Each relay has
its own list of rules.

## How a relay decides

Every 5 seconds, for every relay in Auto:

1. Rules are checked from the **highest priority** down.
2. A rule whose sensor is still **warming up** (just started): the relay keeps
   its current state.
3. A rule whose sensor is **not answering** (10 min without a good reading; Victron
   devices 2 min): the relay switches **off**. A heater never keeps running on a
   dead sensor.
4. The first rule whose condition **matches** decides: its action (on or off).
5. No rule matches, or no rules at all: **off**.

Then two kinds of protection may delay a change (never a safety "off"):

* the relay's **minimum on / off time** (protects compressors, pumps, heaters
  from rapid switching), and
* the **cooldown** of the rule that made the last change.

The dashboard shows why a relay is in its state, and what it is waiting for.

On top of all rules, a relay can have a **safety cutoff**: above a temperature
it is forced off in every mode, manual included, until it has cooled 1 °C below
the limit.

**Manual** mode (On/Off in the dashboard) ignores the rules, optionally for a
limited time, after which the relay returns to Auto.

## Writing rules in the dashboard

Open a relay (Switches → tap its name) → **Add rule**:

> When **Temperature** of **inside** **is below** **8** → switch the relay **On**

| Field | Meaning |
|---|---|
| When | `Temperature`, `Humidity` (DHT22 sensors) or `Battery %`, `Battery voltage`, `Battery current`, `Solar power` (Victron devices) |
| of | Which sensor or device |
| is below / above / between | `between 8 and 12` matches from 8 up to (not including) 12 |
| Priority | Higher wins when several rules match. Default 100. |
| Cooldown | After this rule switched the relay, keep that state at least this long |

### Heating like a thermostat

Rules have no memory of the relay's state, so "on below 8 °C, off above 12 °C,
keep whatever it is in between" (hysteresis) is not possible with rules alone.
What works well in practice:

| Setting | Value |
|---|---|
| Rule | inside temperature below **10** → **on** |
| Rule cooldown | 10 min |
| Relay minimum on time | 15 min |

The heater starts below 10 °C and then runs at least 15 minutes, so it does
not chatter around the threshold. Add a **safety cutoff** (e.g. 30 °C) on the
relay as well.

### Priorities in practice

| Rule | Priority | Action |
|---|---|---|
| Battery below 20 % (`battery_soc` of `shunt`) | 900 | off |
| inside below 8 °C | 100 | on |

When the battery is low, the higher priority wins and the heater stays off.

## Combined conditions (JSON)

**More options → Edit as JSON** accepts any combination:

```json
{ "type": "threshold", "metric": "temperature", "sensor": "inside", "op": "<", "value": 8 }
{ "type": "range",     "metric": "humidity",    "sensor": "inside", "min": 40, "max": 70 }
{ "type": "all", "conditions": [ … ] }     // every condition matches
{ "type": "any", "conditions": [ … ] }     // at least one matches
{ "type": "not", "condition": { … } }
{ "type": "always" }
```

`op` is one of `<`, `<=`, `>`, `>=`. `metric` is `temperature`, `humidity`,
`battery_soc`, `battery_voltage`, `battery_current` or `solar_power`.
Conditions can be nested up to 4 levels.

Example: fan on when it's warm inside **and** the battery is above 50 %:

```json
{
  "type": "all",
  "conditions": [
    { "type": "threshold", "metric": "temperature", "sensor": "inside", "op": ">", "value": 26 },
    { "type": "threshold", "metric": "battery_soc", "sensor": "shunt", "op": ">", "value": 50 }
  ]
}
```

If any sensor in a combined condition stops answering, the whole rule counts
as "not answering" and the relay goes off.

## From the remote dashboard

Rules can be added and changed remotely too. The change reaches the van on its
next sync; if that rule was changed on the van in the meantime, the van's
version wins and the remote dashboard says so.
