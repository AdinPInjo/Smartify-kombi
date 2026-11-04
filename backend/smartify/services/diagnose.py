# ruff: noqa: E501  (plain-language hints: long sentences read better unbroken)
"""Plain-language hints for "Diagnose" in the Sensors tab: what the readings say
about the wiring, and what to check first."""

from __future__ import annotations

from typing import Any

GPIO_TO_PIN = {
    2: 3,
    3: 5,
    4: 7,
    17: 11,
    27: 13,
    22: 15,
    10: 19,
    9: 21,
    11: 23,
    5: 29,
    6: 31,
    13: 33,
    19: 35,
    26: 37,
    14: 8,
    15: 10,
    18: 12,
    23: 16,
    24: 18,
    25: 22,
    8: 24,
    7: 26,
    12: 32,
    16: 36,
    20: 38,
    21: 40,
}


def _pin(config: dict[str, Any]) -> str:
    gpio = config.get("pin")
    return f"GPIO {gpio} (pin {GPIO_TO_PIN.get(gpio, '?')})" if gpio is not None else "its data pin"


def climate_hints(
    kind: str, config: dict[str, Any], reads: int, good: int, errors: list[str]
) -> list[str]:
    if reads < 5:
        return ["Collecting readings: give it a minute."]
    rate = good / reads
    text = " ".join(errors).lower()
    hints: list[str] = []
    if good == 0:
        if kind in ("dht22", "dht11"):
            hints.append(
                f"No reading at all. Check the three wires: + to pin 1 (3.3 V), − to a ground pin, "
                f"data to {_pin(config)}. Swapped + and − can damage the sensor."
            )
            hints.append("A bare sensor (4 legs) needs a 10 kΩ resistor between data and 3.3 V.")
        elif kind == "ds18b20":
            if "not found" in text:
                hints.append(
                    "The probe isn't on the 1-Wire bus: check the yellow wire is on the "
                    "1-Wire pin and the "
                    "4.7 kΩ resistor sits between yellow and red (3.3 V)."
                )
            if "starting" in text:
                hints.append(
                    "The probe only reports 85 °C (its power-on value): its red wire needs 3.3 V."
                )
        else:
            hints.append(
                "The sensor doesn't answer on I2C: SDA to pin 3, SCL to pin 5 (often swapped), "
                "VIN to 3.3 V."
            )
            hints.append(
                "Check the address: some boards use the second address (try the other one in Edit)."
            )
        return hints or ["No reading yet. Check power, ground and the data wire."]
    if rate < 0.7 and kind in ("dht22", "dht11"):
        hints.append(
            f"{round((1 - rate) * 100)} % of reads fail. A DHT22 fails now and then, "
            "but this many points to a loose "
            "data wire, a cable longer than about 20 m, or a missing pull-up resistor."
        )
    elif rate < 0.9 and kind not in ("dht22", "dht11"):
        hints.append(
            f"{round((1 - rate) * 100)} % of reads fail: "
            "check for loose wires and keep cables short."
        )
    if "implausible" in text:
        hints.append(
            "Some values were impossible (e.g. 100 % humidity or −40 °C): typical for a damaged or wet sensor."
        )
    if not hints:
        hints.append(f"Looks good: {round(rate * 100)} % of reads worked in the last hour.")
    return hints


def input_hints(kind: str, config: dict[str, Any], data: dict[str, Any]) -> list[str]:
    if data["error"]:
        return [f"The Pi can't read {_pin(config)}: {data['error']}"]
    if not data["changes"]:
        if kind == "door":
            return [
                "It hasn't changed yet. Open and close the door while watching this page.",
                f"If it never changes: one wire to {_pin(config)}, the other to a ground pin; the magnet within "
                "about 1 cm of the switch when the door is shut.",
            ]
        return [
            "No motion seen yet. Wave in front of it; after power-up a PIR needs up to a minute to settle.",
            "Still nothing: turn its sensitivity knob up and its time knob to the shortest setting.",
        ]
    hints = ["Works: every change is listed below."]
    if kind == "door" and data["active"] and len(data["changes"]) == 1:
        hints.append(
            "It says open: if the door is shut, choose the other 'closed when' setting in Edit."
        )
    return hints


def gps_hints(status: str, satellites: int | None, error: str | None) -> list[str]:
    if status == "ok":
        return [f"Works: position from {satellites or '–'} satellites."]
    if error and ("No such file" in error or "could not open" in error.lower()):
        return [
            "The serial port doesn't exist: the Pi's serial port may be switched off (run the installer once more)."
        ]
    return [
        "No position yet. The first one takes up to 5 minutes, outdoors or with the antenna under a plastic roof.",
        "Still nothing after 10 minutes: TX and RX are often swapped. GPS TX goes to pin 10, GPS RX to pin 8.",
    ]


def water_hints(reading: Any) -> list[str]:
    if reading.ok:
        hints = [
            f"Works: {reading.level_percent} % (signal {reading.signal_voltage:.3f} V, battery {reading.battery_voltage:.2f} V)."
        ]
        if reading.battery_voltage is not None and reading.battery_voltage < 10:
            hints.append("The battery reads under 10 V: check the 47k/10k divider on A1.")
        return hints
    return [
        f"No reading: {reading.error}.",
        "Check the ADS1115: VDD to 3.3 V, GND, SDA to pin 3, SCL to pin 5; the sender on A0, the divider on A1.",
    ]
