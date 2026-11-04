"""Sensor drivers on the Raspberry Pi, built from the dashboard's sensor list.

- DHT22 / DHT11: ``adafruit-circuitpython-dht`` (see dht22.py)
- DS18B20: the kernel's 1-Wire driver (``dtoverlay=w1-gpio``), read from /sys
- BME280, SHT31, AHT20: Adafruit's CircuitPython drivers over I2C
- Door contacts, motion sensors: GPIO inputs through libgpiod
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from smartify.hardware.base import ClimateReading, HardwareError, InputState, SensorConfig

log = logging.getLogger(__name__)

W1_DEVICES = Path("/sys/bus/w1/devices")
I2C_BUS = 1
_I2C_LOCK = threading.Lock()


class Ds18b20Sensor:
    def __init__(self, name: str, rom: str, root: Path = W1_DEVICES) -> None:
        self.name = name
        self._path = root / rom

    def read(self) -> ClimateReading:
        try:
            simple = self._path / "temperature"
            if simple.exists():
                value = int(simple.read_text().strip()) / 1000
            else:
                lines = (self._path / "w1_slave").read_text().splitlines()
                if len(lines) < 2 or not lines[0].strip().endswith("YES"):
                    return ClimateReading(
                        self.name, None, None, error="checksum error, reading again"
                    )
                value = int(lines[1].split("t=")[1]) / 1000
        except FileNotFoundError:
            return ClimateReading(
                self.name, None, None, error="probe not found on the 1-Wire bus (wiring?)"
            )
        except (OSError, ValueError, IndexError) as exc:
            return ClimateReading(self.name, None, None, error=f"read failed: {exc}")
        if value == 85.0:
            # 85 °C is the probe's power-on value: not a real reading yet.
            return ClimateReading(self.name, None, None, error="probe still starting")
        return ClimateReading(self.name, round(value, 2), None)


class I2cClimateSensor:
    """BME280, SHT31 or AHT20 through Adafruit's drivers."""

    def __init__(self, name: str, kind: str, address: int) -> None:
        self.name = name
        self.kind = kind
        self.address = address
        self._device: Any = None

    def _open(self) -> Any:
        try:
            import board

            i2c = board.I2C()
            if self.kind == "bme280":
                from adafruit_bme280 import basic as bme280

                return bme280.Adafruit_BME280_I2C(i2c, address=self.address)
            if self.kind == "sht31":
                import adafruit_sht31d

                return adafruit_sht31d.SHT31D(i2c, address=self.address)
            import adafruit_ahtx0

            return adafruit_ahtx0.AHTx0(i2c, address=self.address)
        except ImportError as exc:
            raise HardwareError(
                f"the {self.kind.upper()} driver is missing: update Smartify (Settings → Updates)"
            ) from exc

    def read(self) -> ClimateReading:
        with _I2C_LOCK:
            try:
                if self._device is None:
                    self._device = self._open()
                temperature = float(self._device.temperature)
                humidity = float(self._device.relative_humidity)
            except HardwareError as exc:
                return ClimateReading(self.name, None, None, error=str(exc))
            except (OSError, ValueError, RuntimeError) as exc:
                self._device = None  # try again from scratch next time
                return ClimateReading(
                    self.name, None, None, error=f"no answer at {hex(self.address)}: {exc}"
                )
        return ClimateReading(self.name, round(temperature, 2), round(humidity, 1))


# The 40-pin header's GPIO controller: the same pins on every Pi with a 40-pin
# header, but a different chip inside (Pi 3: bcm2835, Pi 4: bcm2711, Pi 5: RP1).
HEADER_CHIPS = ("pinctrl-rp1", "pinctrl-bcm2711", "pinctrl-bcm2835")


def header_chip() -> str:
    try:
        import gpiod

        for path in sorted(Path("/dev").glob("gpiochip*")):
            try:
                with gpiod.Chip(str(path)) as chip:
                    if chip.get_info().label in HEADER_CHIPS:
                        return str(path)
            except OSError:
                continue
    except ImportError:  # pragma: no cover - depends on the Pi
        pass
    return "/dev/gpiochip0"


class GpioInput:
    """A door contact (to ground, with the Pi's pull-up) or a motion sensor output."""

    def __init__(self, name: str, kind: str, pin: int, closed_when: str = "low") -> None:
        self.name = name
        self.kind = kind
        self.pin = pin
        self._closed_when = closed_when
        self._request: Any = None

    def _open(self) -> Any:
        try:
            import gpiod
            from gpiod.line import Bias, Direction
        except ImportError as exc:  # pragma: no cover - depends on the Pi
            raise HardwareError("GPIO inputs need the 'gpiod' package (update Smartify)") from exc
        bias = Bias.PULL_UP if self.kind == "door" else Bias.PULL_DOWN
        return gpiod.request_lines(
            header_chip(),
            consumer=f"smartify-{self.name}",
            config={self.pin: gpiod.LineSettings(direction=Direction.INPUT, bias=bias)},
        )

    def read(self) -> InputState:
        try:
            if self._request is None:
                self._request = self._open()
            from gpiod.line import Value

            high = self._request.get_value(self.pin) == Value.ACTIVE
        except Exception as exc:  # noqa: BLE001 - GPIO busy, permissions, ...
            self._request = None
            return InputState(None, f"cannot read GPIO {self.pin}: {exc}")
        if self.kind == "motion":
            return InputState(high)
        closed = (not high) if self._closed_when == "low" else high
        return InputState(not closed)


class PiSensorFactory:
    def __init__(self, analog: Any = None) -> None:
        self._analog = analog

    def climate(self, config: SensorConfig) -> Any:
        if config.kind in ("dht22", "dht11"):
            from smartify.hardware.pi.dht22 import Dht22Sensor

            return Dht22Sensor(config.name, int(config.config["pin"]), model=config.kind)
        if config.kind == "ds18b20":
            return Ds18b20Sensor(config.name, config.config["rom"])
        return I2cClimateSensor(config.name, config.kind, int(config.config["address"]))

    def input(self, config: SensorConfig) -> GpioInput:
        return GpioInput(
            config.name,
            config.kind,
            int(config.config["pin"]),
            config.config.get("closed_when", "low"),
        )

    def discover(self) -> dict[str, Any]:
        onewire = {
            "enabled": W1_DEVICES.exists() and any(W1_DEVICES.glob("w1_bus_master*")),
            "probes": [],
        }
        if W1_DEVICES.exists():
            onewire["probes"] = sorted(p.name for p in W1_DEVICES.glob("28-*"))
        i2c: dict[str, Any] = {"enabled": Path(f"/dev/i2c-{I2C_BUS}").exists(), "addresses": []}
        if i2c["enabled"]:
            try:
                from smbus2 import SMBus

                with _I2C_LOCK, SMBus(I2C_BUS) as bus:
                    for address in range(0x08, 0x78):
                        try:
                            bus.read_byte(address)
                            i2c["addresses"].append(address)
                        except OSError:
                            pass
            except Exception as exc:  # noqa: BLE001
                log.info("I2C scan failed: %s", exc)
        return {"onewire": onewire, "i2c": i2c}

    def test(self, kind: str, config: dict[str, Any]) -> dict[str, Any]:
        probe = SensorConfig("test", "test", kind, config)
        try:
            if kind in ("door", "motion"):
                gpio = self.input(probe)
                state = gpio.read()
                if gpio._request is not None:
                    gpio._request.release()
                if state.active is None:
                    return {"ok": False, "text": state.error}
                if kind == "door":
                    return {"ok": True, "text": "open" if state.active else "closed"}
                return {"ok": True, "text": "motion" if state.active else "quiet"}
            if kind == "water_tank":
                if self._analog is None:
                    return {"ok": False, "text": "no ADS1115 found"}
                volts = self._analog.read_voltages((0, 1))
                return {
                    "ok": True,
                    "text": f"ADS1115 answers: A0 {volts[0]:.3f} V, A1 {volts[1]:.3f} V",
                }
            if kind == "gps":
                return {"ok": True, "text": "saved: the Map page shows the GPS after the restart"}
            sensor = self.climate(probe)
            reading = sensor.read()
            if not reading.ok and kind in ("dht22", "dht11"):
                import time

                time.sleep(2.2)  # DHT reads fail now and then: one more try
                reading = sensor.read()
        except HardwareError as exc:
            return {"ok": False, "text": str(exc)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "text": f"{type(exc).__name__}: {exc}"}
        if not reading.ok:
            return {"ok": False, "text": reading.error}
        humidity = f", {reading.humidity:.0f} %" if reading.humidity is not None else ""
        return {"ok": True, "text": f"{reading.temperature_c:.1f} °C{humidity}"}
