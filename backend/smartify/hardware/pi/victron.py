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
import time
from collections.abc import Callable

from smartify.config import VictronDevice
from smartify.hardware.base import DiscoveredVictron, HardwareError, VictronReading
from smartify.hardware.victron import (
    VICTRON_MANUFACTURER_ID,
    decode,
    is_instant_readout,
    kind_of,
)

log = logging.getLogger(__name__)

_RETRY_SECONDS = 30


def _explain(exc: Exception) -> str:
    """A scan error in words a van owner can act on."""
    text = str(exc)
    if "POWERED_OFF" in text or "No powered Bluetooth" in text:
        return (
            "Bluetooth is switched off on the Pi. Turn it on once with: "
            "sudo rfkill unblock bluetooth && bluetoothctl power on"
        )
    if "NO_BLUETOOTH" in text or "No Bluetooth adapters" in text:
        return "This Pi has no Bluetooth adapter (or it is disabled in /boot/firmware/config.txt)."
    if "org.bluez" in text or "ServiceUnknown" in text:
        return (
            "The Bluetooth service is not running. "
            "Start it with: sudo systemctl enable --now bluetooth"
        )
    return f"Bluetooth not available: {text}"


class BleVictronListener:
    """Listens all the time, even without configured devices, so the dashboard
    can show the Victron devices nearby while you set them up."""

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
        # Every Victron seen recently: MAC -> (raw data, BLE name, rssi, seen at)
        self._seen: dict[str, tuple[bytes, str | None, int | None, float]] = {}
        self._scan_error: str | None = None

    def set_devices(self, devices: list[VictronDevice]) -> None:
        """Change the devices to decode, while running."""
        self._devices = {d.mac.upper(): d for d in devices}
        self._errors.clear()

    def discovered(self) -> list[DiscoveredVictron]:
        now = time.time()
        result = []
        for mac, (data, name, rssi, at) in list(self._seen.items()):
            if now - at > 120:
                continue
            result.append(DiscoveredVictron(mac, name, kind_of(data), rssi, int(at)))
        return sorted(result, key=lambda d: -(d.rssi or -999))

    def check_key(self, mac: str, key: str) -> bool | None:
        """Does the key decrypt this device's latest advertisement? None: not heard yet."""
        seen = self._seen.get(mac.upper())
        if seen is None:
            return None
        try:
            decode("check", key, seen[0])
        except HardwareError as exc:
            return "wrong encryption key" not in str(exc)
        return True

    @property
    def error(self) -> str | None:
        return self._scan_error

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
            data = advertisement.manufacturer_data.get(VICTRON_MANUFACTURER_ID)
            if not data or not is_instant_readout(data):
                return
            mac = device.address.upper()
            name = advertisement.local_name or device.name
            self._seen[mac] = (bytes(data), name, advertisement.rssi, time.time())
            config = self._devices.get(mac)
            if config is None:
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
                    self._scan_error = None
                    log.info("Listening for %d Victron device(s)", len(self._devices))
                    await self._stop.wait()
            except Exception as exc:
                self._scan_error = _explain(exc)
                log.error("Bluetooth scan failed (%s), retrying in %d s", exc, _RETRY_SECONDS)
                try:
                    await asyncio.wait_for(self._stop.wait(), _RETRY_SECONDS)
                except TimeoutError:
                    pass
