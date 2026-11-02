"""Relay control through the ``pinctrl`` command.

``pinctrl`` ships with Raspberry Pi OS (Bookworm and later) and works on every
Pi model. Unlike Python GPIO libraries it leaves the pin in the requested state
when the process exits, so restarting Smartify does not flip the relays.
"""

from __future__ import annotations

import shutil
import subprocess

from smartify.hardware.base import HardwareError


class PinctrlRelayDriver:
    def __init__(self, binary: str = "pinctrl") -> None:
        path = shutil.which(binary)
        if path is None:
            raise HardwareError(
                f"'{binary}' not found. Install it with: sudo apt install raspi-utils"
            )
        self._binary = path

    def set_state(self, gpio_pin: int, on: bool, active_low: bool) -> None:
        drive_high = on != active_low
        level = "dh" if drive_high else "dl"
        try:
            result = subprocess.run(
                [self._binary, "set", str(gpio_pin), "op", level],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise HardwareError(f"pinctrl timed out on GPIO {gpio_pin}") from exc
        if result.returncode != 0:
            raise HardwareError(f"pinctrl failed on GPIO {gpio_pin}: {result.stderr.strip()}")
