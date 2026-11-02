"""Simulated hardware for development and tests (``SMARTIFY_HARDWARE=mock``).

Values change slowly over time so the dashboard looks alive, and relays affect
the simulated cabin: a running heater warms it, a running fan cools it.
"""

from __future__ import annotations

import math
import random
import threading
import time

from smartify.hardware.base import ClimateReading, GpsFix, HardwareError


class MockRelayDriver:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.pin_levels: dict[int, bool] = {}
        self.fail_pins: set[int] = set()

    def set_state(self, gpio_pin: int, on: bool, active_low: bool) -> None:
        if gpio_pin in self.fail_pins:
            raise HardwareError(f"simulated failure on GPIO {gpio_pin}")
        with self._lock:
            self.pin_levels[gpio_pin] = on != active_low

    def is_on(self, gpio_pin: int, active_low: bool = False) -> bool:
        with self._lock:
            return self.pin_levels.get(gpio_pin, active_low) != active_low


class MockCabin:
    """Shared simulated environment: cabin temperature reacts to relays."""

    def __init__(self, relays: MockRelayDriver, heater_pin: int | None, fan_pin: int | None):
        self._relays = relays
        self._heater_pin = heater_pin
        self._fan_pin = fan_pin
        self._lock = threading.Lock()
        self._temperature = 12.0
        self._last_update = time.monotonic()

    def temperature(self) -> float:
        with self._lock:
            now = time.monotonic()
            elapsed_min = min((now - self._last_update) / 60.0, 30.0)
            self._last_update = now
            outside = 8.0 + 4.0 * math.sin(time.time() / 3600.0)
            drift = (outside - self._temperature) * 0.05
            if self._heater_pin is not None and self._relays.is_on(self._heater_pin):
                drift += 0.8
            if self._fan_pin is not None and self._relays.is_on(self._fan_pin):
                drift -= 0.3
            self._temperature += drift * elapsed_min
            return self._temperature


class MockClimateSensor:
    def __init__(self, name: str, cabin: MockCabin, offset: float = 0.0, fail_rate: float = 0.05):
        self.name = name
        self._cabin = cabin
        self._offset = offset
        self._fail_rate = fail_rate

    def read(self) -> ClimateReading:
        # DHT22 reads fail now and then on real hardware too.
        if random.random() < self._fail_rate:
            return ClimateReading(self.name, None, None, error="simulated checksum error")
        temperature = self._cabin.temperature() + self._offset + random.uniform(-0.1, 0.1)
        humidity = 55.0 + 10.0 * math.sin(time.time() / 1800.0) + random.uniform(-1, 1)
        return ClimateReading(self.name, round(temperature, 1), round(humidity, 1))


class MockAnalogReader:
    """Water tank that slowly empties and refills, on a battery that charges and drains.

    Channel 0 = sender signal, channel 1 = battery through a 47k/10k divider.
    The sender output follows the battery voltage, like a real resistive sender:
    signal = battery * ratio, with ratio 0.037 (full) to 0.163 (empty).
    """

    full_ratio = 0.037
    empty_ratio = 0.163
    divider = 10_000 / 57_000

    def battery_voltage(self) -> float:
        return 12.9 + 0.6 * math.sin(time.time() / 5400.0)

    def read_voltages(self, channels: tuple[int, ...]) -> tuple[float, ...]:
        level = 0.5 + 0.5 * math.cos(time.time() / 7200.0)  # 1.0 = full
        battery = self.battery_voltage()
        ratio = self.empty_ratio - level * (self.empty_ratio - self.full_ratio)
        values = {0: battery * ratio, 1: battery * self.divider, 2: 0.0, 3: 0.0}
        return tuple(round(values[ch] + random.uniform(-0.002, 0.002), 4) for ch in channels)


class MockGpsReceiver:
    """Parked van with small position jitter, occasionally driving a loop."""

    def __init__(self, lat: float = 44.2269, lon: float = 17.6658) -> None:
        self._lat = lat
        self._lon = lon

    def read_fix(self, timeout_seconds: float) -> GpsFix | None:
        t = time.time()
        driving = int(t // 600) % 3 == 0  # drive 10 min out of every 30
        if driving:
            angle = t / 300.0
            lat = self._lat + 0.01 * math.sin(angle)
            lon = self._lon + 0.01 * math.cos(angle)
            speed = 45.0 + random.uniform(-5, 5)
            course = (math.degrees(angle) + 90) % 360
        else:
            lat = self._lat + random.uniform(-0.00002, 0.00002)
            lon = self._lon + random.uniform(-0.00002, 0.00002)
            speed, course = 0.0, None
        return GpsFix(lat, lon, speed, course, altitude_m=512.0, satellites=8)

    def close(self) -> None:
        pass


class MockVictronListener:
    """Simulated SmartShunt, SmartSolar MPPT, Orion DC-DC and MultiPlus (VE.Bus).

    Solar follows the time of day; the battery charges in daylight and drains
    at night. Field names match what ``victron-ble`` produces on real devices.
    """

    def __init__(self, interval: float = 3.0) -> None:
        self._interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, on_reading) -> None:
        def loop() -> None:
            while not self._stop.is_set():
                for reading in self.readings():
                    on_reading(reading)
                self._stop.wait(self._interval)

        self._thread = threading.Thread(target=loop, name="mock-victron", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    @staticmethod
    def readings(now: float | None = None) -> list:
        from smartify.hardware.base import VictronReading

        now = time.time() if now is None else now
        hour = time.localtime(now).tm_hour + time.localtime(now).tm_min / 60
        sun = max(0.0, math.sin((hour - 6) / 14 * math.pi)) if 6 <= hour <= 20 else 0.0
        solar_power = round(380 * sun * (0.8 + 0.2 * random.random()))
        load_amps = 3.5 + 1.5 * random.random()
        battery_current = round(solar_power / 13.4 - load_amps, 2)
        soc = round(55 + 30 * math.sin(now / 21600), 1)
        voltage = round(12.8 + 0.6 * sun + (soc - 50) / 200, 2)
        charge_state = "off" if solar_power < 5 else ("bulk" if soc < 80 else "float")
        driving = int(now // 600) % 3 == 0
        ac_out = round(60 + 40 * random.random())
        return [
            VictronReading(
                "shunt",
                "battery_monitor",
                "SmartShunt 500A/50mV",
                {
                    "voltage": voltage,
                    "current": battery_current,
                    "soc": soc,
                    "consumed_ah": round(-(100 - soc) * 6, 1),
                    "remaining_mins": None
                    if battery_current >= 0
                    else int(soc * 6 / -battery_current * 60),
                    "alarm": "no_alarm",
                    "aux_mode": "starter_voltage",
                    "starter_voltage": 12.6 if not driving else 14.1,
                },
                rssi=-62,
            ),
            VictronReading(
                "solar",
                "solar_charger",
                "SmartSolar MPPT 100|30",
                {
                    "charge_state": charge_state,
                    "charger_error": "no_error",
                    "battery_voltage": voltage,
                    "battery_charging_current": round(solar_power / max(voltage, 1), 1),
                    "solar_power": solar_power,
                    "yield_today": round(380 * min(max(0.0, hour - 6), 14) / 14 * 6 * 0.6),  # Wh
                    "external_device_load": 0.0,
                },
                rssi=-70,
            ),
            VictronReading(
                "orion",
                "dcdc_converter",
                "Orion XS 12|12-50A",
                {
                    "charge_state": "bulk" if driving else "off",
                    "charger_error": "no_error",
                    "input_voltage": 14.1 if driving else 12.6,
                    "output_voltage": 14.2 if driving else voltage,
                    "input_current": 32.0 if driving else 0.0,
                    "output_current": 30.5 if driving else 0.0,
                    "off_reason": "no_reason" if driving else "engine_shutdown",
                },
                rssi=-75,
            ),
            VictronReading(
                "multiplus",
                "inverter_charger",
                "MultiPlus 12|800|35",
                {
                    "device_state": "inverting",
                    "error": 0,
                    "alarm": None,
                    "ac_in_state": "not_connected",
                    "ac_in_power": 0,
                    "ac_out_power": ac_out,
                    "battery_voltage": voltage,
                    "battery_current": round(-ac_out / 12, 1),
                    "battery_temperature": 18,
                    "soc": soc,
                },
                rssi=-68,
            ),
        ]
