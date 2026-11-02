"""Listen for Victron Instant Readout advertisements with BlueZ (via bleak).

Runs its own asyncio loop in a background thread. If the Bluetooth adapter is
unavailable (rfkill, BlueZ restart) it keeps retrying every 30 seconds.

Note: on a Pi 3B, WiFi and Bluetooth share one radio. Passive scanning is
light, but heavy WiFi traffic and Bluetooth can slow each other down.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable

from smartify.config import VictronDevice
from smartify.hardware.base import HardwareError, VictronReading
from smartify.hardware.victron import VICTRON_MANUFACTURER_ID, decode, is_instant_readout

log = logging.getLogger(__name__)

_RETRY_SECONDS = 30


class BleVictronListener:
    def __init__(self, devices: list[VictronDevice]) -> None:
        try:
            import bleak  # noqa: F401
        except ImportError as exc:  # pragma: no cover - depends on the Pi
            raise HardwareError(
                "Victron support needs the 'pi' extras: pip install 'smartify-kombi[pi]'"
            ) from exc
        self._devices = {d.mac.upper(): d for d in devices}
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop: asyncio.Event | None = None
        self._errors: dict[str, str] = {}

    def start(self, on_reading: Callable[[VictronReading], None]) -> None:
        self._thread = threading.Thread(
            target=self._run, args=(on_reading,), name="victron-ble", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        if self._loop is not None and self._stop is not None:
            self._loop.call_soon_threadsafe(self._stop.set)
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self, on_reading: Callable[[VictronReading], None]) -> None:
        self._loop = asyncio.new_event_loop()
        try:
            self._loop.run_until_complete(self._scan_forever(on_reading))
        finally:
            self._loop.close()

    async def _scan_forever(self, on_reading: Callable[[VictronReading], None]) -> None:
        from bleak import BleakScanner

        self._stop = asyncio.Event()

        def detected(device, advertisement) -> None:
            config = self._devices.get(device.address.upper())
            if config is None:
                return
            data = advertisement.manufacturer_data.get(VICTRON_MANUFACTURER_ID)
            if not data or not is_instant_readout(data):
                return
            try:
                reading = decode(config.name, config.key, data, advertisement.rssi)
            except HardwareError as exc:
                if self._errors.get(config.name) != str(exc):
                    log.warning("%s", exc)  # log each distinct problem once
                    self._errors[config.name] = str(exc)
                return
            self._errors.pop(config.name, None)
            on_reading(reading)

        while not self._stop.is_set():
            try:
                async with BleakScanner(detection_callback=detected):
                    log.info("Listening for %d Victron device(s)", len(self._devices))
                    await self._stop.wait()
            except Exception as exc:
                log.error("Bluetooth scan failed (%s), retrying in %d s", exc, _RETRY_SECONDS)
                try:
                    await asyncio.wait_for(self._stop.wait(), _RETRY_SECONDS)
                except TimeoutError:
                    pass
