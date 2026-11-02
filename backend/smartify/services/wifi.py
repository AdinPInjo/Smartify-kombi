"""WiFi through NetworkManager (``nmcli``), the default on Raspberry Pi OS Bookworm.

The service user must be allowed to manage NetworkManager. The default user
created by Raspberry Pi Imager is; for a dedicated user see docs/install.md.

Note for the dashboard: switching networks drops the connection the browser is
using if it reaches the Pi over that same WiFi.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import Protocol


class WifiError(RuntimeError):
    pass


@dataclass(frozen=True)
class WifiNetwork:
    ssid: str
    signal: int
    secured: bool
    in_use: bool


@dataclass(frozen=True)
class WifiStatus:
    available: bool
    connected: bool
    ssid: str | None
    ip_address: str | None
    error: str | None = None


class WifiBackend(Protocol):
    def status(self) -> WifiStatus: ...
    def scan(self) -> list[WifiNetwork]: ...
    def connect(self, ssid: str, password: str | None) -> None: ...


def split_terse(line: str) -> list[str]:
    """Split an ``nmcli -t`` line: fields separated by ':', with '\\:' and '\\\\' escaped."""
    fields, current, escaped = [], [], False
    for char in line:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ":":
            fields.append("".join(current))
            current = []
        else:
            current.append(char)
    fields.append("".join(current))
    return fields


def parse_scan(output: str) -> list[WifiNetwork]:
    """Parse ``nmcli -t -f IN-USE,SSID,SIGNAL,SECURITY device wifi list``.

    Hidden networks are skipped; for each SSID the strongest access point is kept.
    """
    best: dict[str, WifiNetwork] = {}
    for line in output.splitlines():
        parts = split_terse(line)
        if len(parts) < 4 or not parts[1]:
            continue
        in_use, ssid, signal, security = parts[0], parts[1], parts[2], parts[3]
        network = WifiNetwork(
            ssid=ssid,
            signal=int(signal) if signal.isdigit() else 0,
            secured=security not in ("", "--"),
            in_use=in_use.strip() == "*",
        )
        previous = best.get(ssid)
        if (
            previous is None
            or network.in_use
            or (not previous.in_use and network.signal > previous.signal)
        ):
            best[ssid] = network
    return sorted(best.values(), key=lambda n: (not n.in_use, -n.signal, n.ssid.lower()))


class NmcliWifi:
    def __init__(self, interface: str = "wlan0") -> None:
        self.interface = interface
        self._nmcli = shutil.which("nmcli")

    def _run(self, *args: str, timeout: float = 20) -> str:
        if self._nmcli is None:
            raise WifiError("nmcli not found; NetworkManager is required for WiFi control")
        try:
            result = subprocess.run(
                [self._nmcli, *args], capture_output=True, text=True, timeout=timeout, check=False
            )
        except subprocess.TimeoutExpired as exc:
            raise WifiError("nmcli timed out") from exc
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip()
            raise WifiError(message.removeprefix("Error: ") or "nmcli failed")
        return result.stdout

    def status(self) -> WifiStatus:
        try:
            output = self._run(
                "-t",
                "-f",
                "GENERAL.STATE,GENERAL.CONNECTION,IP4.ADDRESS",
                "device",
                "show",
                self.interface,
            )
        except WifiError as exc:
            return WifiStatus(False, False, None, None, str(exc))
        values: dict[str, str] = {}
        for line in output.splitlines():
            key, _, value = line.partition(":")
            values.setdefault(key.split("[")[0], value)
        connected = values.get("GENERAL.STATE", "").startswith("100")
        ip = values.get("IP4.ADDRESS", "").split("/")[0] or None
        ssid = self._active_ssid() if connected else None
        return WifiStatus(True, connected, ssid, ip)

    def _active_ssid(self) -> str | None:
        # GENERAL.CONNECTION is the profile name (e.g. "preconfigured"), not the SSID.
        try:
            output = self._run(
                "-t",
                "-f",
                "ACTIVE,SSID",
                "device",
                "wifi",
                "list",
                "ifname",
                self.interface,
                "--rescan",
                "no",
            )
        except WifiError:
            return None
        for line in output.splitlines():
            parts = split_terse(line)
            if len(parts) >= 2 and parts[0] == "yes":
                return parts[1] or None
        return None

    def scan(self) -> list[WifiNetwork]:
        output = self._run(
            "-t",
            "-f",
            "IN-USE,SSID,SIGNAL,SECURITY",
            "device",
            "wifi",
            "list",
            "ifname",
            self.interface,
            "--rescan",
            "yes",
        )
        return parse_scan(output)

    def connect(self, ssid: str, password: str | None) -> None:
        args = ["-w", "40", "device", "wifi", "connect", ssid]
        if password:
            args += ["password", password]
        self._run(*args, "ifname", self.interface, timeout=45)


class MockWifi:
    def __init__(self) -> None:
        self.connected_ssid: str | None = "Kombi-Hotspot"
        self.networks = {
            "Kombi-Hotspot": ("hotspot-pass", 78),
            "Camping Free WiFi": (None, 54),
            "Cafe Bosna": ("kahva123", 31),
        }

    def status(self) -> WifiStatus:
        connected = self.connected_ssid is not None
        return WifiStatus(
            True, connected, self.connected_ssid, "192.168.4.23" if connected else None
        )

    def scan(self) -> list[WifiNetwork]:
        return sorted(
            (
                WifiNetwork(ssid, signal, password is not None, ssid == self.connected_ssid)
                for ssid, (password, signal) in self.networks.items()
            ),
            key=lambda n: (not n.in_use, -n.signal),
        )

    def connect(self, ssid: str, password: str | None) -> None:
        if ssid not in self.networks:
            raise WifiError(f"No network with SSID '{ssid}' found.")
        expected, _ = self.networks[ssid]
        if expected is not None and password != expected:
            raise WifiError("Secrets were required, but not provided.")
        self.connected_ssid = ssid
