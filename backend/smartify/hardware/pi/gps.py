"""Serial NMEA GPS receiver (e.g. NEO-6M on /dev/serial0 or a USB dongle)."""

from __future__ import annotations

import logging
import time

from smartify.hardware import nmea, ubx
from smartify.hardware.base import GpsFix, HardwareError

log = logging.getLogger(__name__)

_ACK_TIMEOUT = 1.5


class SerialGpsReceiver:
    def __init__(self, device: str, baud: int = 9600, ublox_tuning: bool = True) -> None:
        try:
            import serial
        except ImportError as exc:  # pragma: no cover - depends on the Pi
            raise HardwareError(
                "GPS support needs the 'pi' extras: pip install 'smartify-kombi[pi]'"
            ) from exc
        self._serial_module = serial
        self.device = device
        self.baud = baud
        self.ublox_tuning = ublox_tuning
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
            if self.ublox_tuning:
                self._tune(self._port)
        return self._port

    def _tune(self, port) -> None:
        """Send the u-blox settings (static hold, SBAS). Best effort: never stops the GPS."""
        for name, msg_class, msg_id, message in ubx.TUNING:
            try:
                port.write(message)
                port.flush()
                answer = self._wait_ack(port, msg_class, msg_id)
            except (OSError, self._serial_module.SerialException) as exc:
                log.warning("GPS tuning (%s) could not be sent: %s", name, exc)
                return
            if answer is True:
                log.info("GPS tuning applied: %s", name)
            elif answer is False:
                log.warning("GPS refused tuning (%s); not a u-blox receiver?", name)
            else:
                log.warning("GPS did not confirm tuning (%s); not a u-blox receiver?", name)

    @staticmethod
    def _wait_ack(port, msg_class: int, msg_id: int) -> bool | None:
        buffer = b""
        deadline = time.monotonic() + _ACK_TIMEOUT
        while time.monotonic() < deadline:
            buffer += port.read(max(1, getattr(port, "in_waiting", 0) or 1))
            answer = ubx.find_ack(buffer, msg_class, msg_id)
            if answer is not None:
                return answer
            buffer = buffer[-512:]  # NMEA keeps streaming in between
        return None

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
                    hdop=gga.hdop if gga else None,
                )
        return None

    def close(self) -> None:
        if self._port is not None:
            try:
                self._port.close()
            finally:
                self._port = None
