"""DHT22 (AM2302) temperature/humidity sensor.

Uses ``adafruit-circuitpython-dht``. DHT22 reads fail regularly by design (the
protocol is timing sensitive), so a failed read is a normal event: it is
reported in the result and the next read usually succeeds. The sensor must not
be read more often than every 2 seconds.
"""

from __future__ import annotations

import threading

from smartify.hardware.base import ClimateReading, HardwareError

# One lock for all DHT22 sensors: reading two of them at the same time on a
# Pi 3 makes both fail far more often.
_READ_LOCK = threading.Lock()


class Dht22Sensor:
    def __init__(self, name: str, gpio_pin: int, model: str = "dht22") -> None:
        try:
            import adafruit_dht
            import board
        except ImportError as exc:  # pragma: no cover - depends on the Pi
            raise HardwareError(
                "DHT22 support needs the 'pi' extras: pip install 'smartify-kombi[pi]'"
            ) from exc

        pin = getattr(board, f"D{gpio_pin}", None)
        if pin is None:
            raise HardwareError(f"GPIO {gpio_pin} is not available on this board")

        self.name = name
        self.gpio_pin = gpio_pin
        kind = adafruit_dht.DHT11 if model == "dht11" else adafruit_dht.DHT22
        self._device = kind(pin, use_pulseio=False)

    def read(self) -> ClimateReading:
        with _READ_LOCK:
            try:
                temperature = self._device.temperature
                humidity = self._device.humidity
            except RuntimeError as exc:
                # Checksum errors, timeouts: expected now and then.
                return ClimateReading(self.name, None, None, error=str(exc))
            except Exception as exc:  # pragma: no cover - depends on the Pi
                return ClimateReading(self.name, None, None, error=f"{type(exc).__name__}: {exc}")

        if temperature is None or humidity is None:
            return ClimateReading(self.name, None, None, error="no data")
        return ClimateReading(self.name, float(temperature), float(humidity))
