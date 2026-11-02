"""Switch every relay off, without the web service.

Run by systemd after the service stops or crashes (``ExecStopPost``), so a
heater is never left running with nothing controlling it::

    python -m smartify.failsafe
"""

from __future__ import annotations

import logging
import sys

from smartify.config import get_settings
from smartify.db import migrate, transaction
from smartify.hardware import HardwareError, build_relay_driver

log = logging.getLogger("smartify.failsafe")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    if not settings.db_path.exists():
        log.info("No database yet, nothing to switch off")
        return 0
    migrate(settings.db_path)
    with transaction(settings.db_path) as conn:
        relays = conn.execute("SELECT name, gpio_pin, active_low FROM relays").fetchall()
    try:
        driver = build_relay_driver(settings)
    except HardwareError as exc:
        log.error("Cannot reach the relays: %s", exc)
        return 1
    failed = 0
    for relay in relays:
        try:
            driver.set_state(relay["gpio_pin"], on=False, active_low=bool(relay["active_low"]))
            log.info("%s (GPIO %d) off", relay["name"], relay["gpio_pin"])
        except HardwareError as exc:
            failed += 1
            log.error("%s (GPIO %d): %s", relay["name"], relay["gpio_pin"], exc)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
