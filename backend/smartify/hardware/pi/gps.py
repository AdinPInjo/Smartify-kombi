"""Serial NMEA GPS receiver (e.g. NEO-6M on /dev/serial0 or a USB dongle)."""

from __future__ import annotations

import time

from smartify.hardware import nmea
from smartify.hardware.base import GpsFix, HardwareError


class SerialGpsReceiver:
    def __init__(self, device: str, baud: int = 9600) -> None:
        try:
            import serial
        except ImportError as exc:  # pragma: no cover - depends on the Pi
            raise HardwareError(
                "GPS support needs the 'pi' extras: pip install 'smartify-kombi[pi]'"
            ) from exc
        self._serial_module = serial
        self.device = device
        self.baud = baud
        self._port = None
        # GGA carries satellites/altitude, RMC carries speed/course.
        # Remember the latest GGA and merge it into the next valid RMC.
        self._last_gga: nmea.GgaSentence | None = None

    def _open(self):
        if self._port is None:
            try:
                self._port = self._serial_module.Serial(self.device, self.baud, timeout=1)
            except (OSError, self._serial_module.SerialException) as exc:
                raise HardwareError(f"Cannot open GPS device {self.device}: {exc}") from exc
        return self._port

    def read_fix(self, timeout_seconds: float) -> GpsFix | None:
        port = self._open()
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            try:
                raw = port.readline()
            except (OSError, self._serial_module.SerialException) as exc:
                self.close()
                raise HardwareError(f"GPS read failed: {exc}") from exc
            sentence = nmea.parse(raw.decode("ascii", errors="ignore"))
            if isinstance(sentence, nmea.GgaSentence):
                self._last_gga = sentence if sentence.has_fix else None
            elif isinstance(sentence, nmea.RmcSentence) and sentence.valid:
                if sentence.lat is None or sentence.lon is None:
                    continue
                gga = self._last_gga
                return GpsFix(
                    lat=sentence.lat,
                    lon=sentence.lon,
                    speed_kmh=sentence.speed_kmh,
                    course=sentence.course,
                    altitude_m=gga.altitude_m if gga else None,
                    satellites=gga.satellites if gga else None,
                )
        return None

    def close(self) -> None:
        if self._port is not None:
            try:
                self._port.close()
            finally:
                self._port = None
