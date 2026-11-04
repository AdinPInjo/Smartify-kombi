"""Diesel heaters over Bluetooth (BlueZ via bleak).

One background thread runs an asyncio loop. Each configured heater gets a task
that keeps a connection open, asks for its status every few seconds and sends
commands. Lessons from the Home Assistant integration this follows: every
Bluetooth call gets a hard timeout (the Pi 3's radio can hang inside BlueZ), a
silent heater is asked again before giving up, and after a failure the
connection starts fresh.

Scanning for heaters only runs while someone looks for one in the dashboard,
so the shared WiFi/Bluetooth radio of a Pi 3 isn't kept busy.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
import time
from typing import Any

from smartify.hardware.base import (
    DiscoveredHeater,
    HardwareError,
    HeaterConfig,
    HeaterLink,
)
from smartify.hardware.heater_protocol import HeaterSession, choose_layout, looks_like_heater

log = logging.getLogger(__name__)

CONNECT_TIMEOUT = 20.0
WRITE_TIMEOUT = 15.0
ANSWER_TIMEOUT = 5.0
POLL_SECONDS = {"hcalory1": 5.0, "hcalory2": 5.0}
DEFAULT_POLL = 15.0
SCAN_SECONDS = 20.0
RETRY = (10, 20, 40, 60)


class _Heater:
    """State of one heater's connection, used from the Bluetooth thread."""

    def __init__(self, config: HeaterConfig) -> None:
        self.config = config
        self.session: HeaterSession | None = None
        self.client: Any = None
        self.write_char: str | None = None
        self.connected = False
        self.error: str | None = "connecting"
        self.last_seen: int | None = None
        self.answer = asyncio.Event()
        self.lock = asyncio.Lock()
        self.task: asyncio.Task | None = None


class BleHeaters:
    def __init__(self) -> None:
        try:
            import bleak  # noqa: F401
        except ImportError as exc:  # pragma: no cover - depends on the Pi
            raise HardwareError(
                "Heater support needs the 'pi' extras: pip install 'smartify-kombi[pi]'"
            ) from exc
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._heaters: dict[str, _Heater] = {}
        self._wanted: list[HeaterConfig] = []
        self._seen: dict[str, DiscoveredHeater] = {}
        self._scan_until = 0.0
        self._scanning = False

    # --- lifecycle ------------------------------------------------------------------

    def start(self) -> None:
        ready = threading.Event()

        def run() -> None:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            ready.set()
            self._loop.run_forever()

        self._thread = threading.Thread(target=run, name="heater-ble", daemon=True)
        self._thread.start()
        ready.wait(5)
        self.set_heaters(self._wanted)

    def stop(self) -> None:
        if self._loop is None:
            return
        try:
            self._call(self._stop_all(), timeout=10)
        except Exception:  # noqa: BLE001 - shutting down anyway
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=5)

    def _call(self, coroutine: Any, timeout: float) -> Any:
        if self._loop is None:
            coroutine.close()
            raise HardwareError("heater support is not running")
        future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        try:
            return future.result(timeout)
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise HardwareError("the heater did not answer in time") from None

    # --- configuration ------------------------------------------------------------------

    def set_heaters(self, heaters: list[HeaterConfig]) -> None:
        self._wanted = list(heaters)
        if self._loop is not None:
            asyncio.run_coroutine_threadsafe(self._apply(list(heaters)), self._loop)

    async def _apply(self, heaters: list[HeaterConfig]) -> None:
        wanted = {h.id: h for h in heaters}
        for heater_id in list(self._heaters):
            current = self._heaters[heater_id]
            if heater_id not in wanted or wanted[heater_id] != current.config:
                await self._drop(heater_id)
        for heater_id, config in wanted.items():
            if heater_id not in self._heaters:
                heater = _Heater(config)
                self._heaters[heater_id] = heater
                heater.task = asyncio.create_task(self._keep_connected(heater))

    async def _drop(self, heater_id: str) -> None:
        heater = self._heaters.pop(heater_id, None)
        if heater is None:
            return
        if heater.task:
            heater.task.cancel()
        await self._disconnect(heater)

    async def _stop_all(self) -> None:
        for heater_id in list(self._heaters):
            await self._drop(heater_id)

    # --- the connection ------------------------------------------------------------------

    async def _keep_connected(self, heater: _Heater) -> None:
        failures = 0
        while True:
            try:
                if not heater.connected:
                    await asyncio.wait_for(self._connect(heater), CONNECT_TIMEOUT)
                    failures = 0
                await self._poll(heater)
                interval = POLL_SECONDS.get(
                    heater.session.transport if heater.session else "", DEFAULT_POLL
                )
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - Bluetooth fails in many ways
                heater.error = _explain(exc)
                if heater.connected or failures == 0:
                    log.warning("Heater %s: %s", heater.config.name, heater.error)
                await self._disconnect(heater)
                await asyncio.sleep(RETRY[min(failures, len(RETRY) - 1)])
                failures += 1

    async def _connect(self, heater: _Heater) -> None:
        from bleak import BleakClient

        heater.error = "connecting"
        client = BleakClient(heater.config.mac, disconnected_callback=lambda _c: _lost(heater))
        await client.connect()
        heater.client = client
        services = {
            service.uuid: {char.uuid: set(char.properties) for char in service.characteristics}
            for service in client.services
        }
        name = getattr(client, "name", None)
        layout = choose_layout(services, name)
        if layout is None:
            await client.disconnect()
            raise HardwareError(
                "this Bluetooth device doesn't look like a supported heater "
                f"(services: {', '.join(sorted(s[4:8] for s in services))})"
            )
        session = HeaterSession(heater.config.mac, heater.config.pin, layout.transport)
        heater.session = session
        heater.write_char = layout.write

        def notified(_char: Any, data: bytearray) -> None:
            if session.feed(bytes(data)) is not None:
                heater.last_seen = int(time.time())
                heater.answer.set()

        await client.start_notify(layout.notify, notified)
        heater.connected = True
        for packet in session.start():
            await self._write(heater, packet)
            await asyncio.sleep(0.5)
        log.info("Heater %s connected (%s layout)", heater.config.name, layout.transport)

    async def _write(self, heater: _Heater, packet: bytes) -> None:
        await asyncio.wait_for(
            heater.client.write_gatt_char(heater.write_char, packet, response=False), WRITE_TIMEOUT
        )

    async def _ask(self, heater: _Heater, packet: bytes) -> bool:
        """Send a packet and wait for a status answer."""
        assert heater.session is not None
        heater.answer.clear()
        await self._write(heater, packet)
        try:
            await asyncio.wait_for(heater.answer.wait(), ANSWER_TIMEOUT)
        except TimeoutError:
            return False
        finally:
            # Handshakes the heater asked for (Sunster V2.1 "locked").
            while heater.session.pending:
                await self._write(heater, heater.session.pending.pop(0))
        return True

    async def _poll(self, heater: _Heater) -> None:
        assert heater.session is not None
        async with heater.lock:
            for attempt in range(3):
                if await self._ask(heater, heater.session.status_request()):
                    heater.error = None
                    return
                if attempt == 1 and heater.session.alternate():
                    log.info(
                        "Heater %s: trying the %s protocol",
                        heater.config.name,
                        heater.session.transport,
                    )
                await asyncio.sleep(1.0)
        raise HardwareError("the heater doesn't answer (wrong PIN, or another phone is connected?)")

    async def _disconnect(self, heater: _Heater) -> None:
        heater.connected = False
        client, heater.client = heater.client, None
        if client is not None:
            try:
                await asyncio.wait_for(client.disconnect(), 10)
            except Exception:  # noqa: BLE001 - already gone
                pass

    # --- for the services --------------------------------------------------------------

    def link(self, heater_id: str) -> HeaterLink:
        heater = self._heaters.get(heater_id)
        if heater is None:
            return HeaterLink(False, None, "connecting", None)
        status = heater.session.status if heater.session else None
        return HeaterLink(
            heater.connected and heater.error is None, status, heater.error, heater.last_seen
        )

    def command(self, heater_id: str, command: int, argument: int = 0) -> None:
        self._call(
            self._command(heater_id, command, argument), timeout=WRITE_TIMEOUT + ANSWER_TIMEOUT + 5
        )

    async def _command(self, heater_id: str, command: int, argument: int) -> None:
        heater = self._heaters.get(heater_id)
        if heater is None or not heater.connected or heater.session is None:
            raise HardwareError("the heater is not connected")
        async with heater.lock:
            await self._write(heater, heater.session.command(command, argument))
            await asyncio.sleep(0.4)
            await self._ask(heater, heater.session.status_request())

    def discovered(self) -> list[DiscoveredHeater]:
        """Heaters nearby; each call keeps a short scan going."""
        self._scan_until = time.time() + SCAN_SECONDS
        if self._loop is not None and not self._scanning:
            self._scanning = True
            asyncio.run_coroutine_threadsafe(self._scan(), self._loop)
        now = time.time()
        return sorted(
            (d for d in self._seen.values() if now - d.seen_at < 120),
            key=lambda d: -(d.rssi or -999),
        )

    async def _scan(self) -> None:
        from bleak import BleakScanner

        def detected(device: Any, advertisement: Any) -> None:
            name = advertisement.local_name or device.name
            if looks_like_heater(
                name, advertisement.manufacturer_data, advertisement.service_uuids
            ):
                mac = device.address.upper()
                self._seen[mac] = DiscoveredHeater(mac, name, advertisement.rssi, int(time.time()))

        try:
            async with BleakScanner(detection_callback=detected):
                while time.time() < self._scan_until:
                    await asyncio.sleep(1)
        except Exception as exc:  # noqa: BLE001
            log.warning("Heater scan failed: %s", exc)
        finally:
            self._scanning = False


def _lost(heater: _Heater) -> None:
    heater.connected = False
    heater.error = "connection lost"


def _explain(exc: Exception) -> str:
    text = str(exc) or type(exc).__name__
    if isinstance(exc, TimeoutError | asyncio.TimeoutError):
        return "no answer over Bluetooth (out of range, or the heater has no power?)"
    if "not found" in text.lower() or "was not found" in text:
        return "not found nearby (out of range, or the heater has no power?)"
    if "POWERED_OFF" in text or "No powered Bluetooth" in text:
        return "Bluetooth is switched off on the Pi"
    return text
