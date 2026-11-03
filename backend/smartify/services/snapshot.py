"""The live state uploaded to the remote dashboard.

Built from the same functions that answer the local API, so the remote
dashboard receives exactly the shapes the local one does.
"""

from __future__ import annotations

from typing import Any

from smartify import __version__

_DEVICE = "device"  # stands in for the logged-in user when calling API functions


def build_state(ctx: Any) -> dict[str, Any]:
    from smartify.api import relays, sensors, system

    relay_list = relays.list_relays(ctx, _DEVICE)["relays"]
    return {
        "version": __version__,
        "relays": relay_list,
        "rules": {r["id"]: relays.list_rules(r["id"], ctx, _DEVICE) for r in relay_list},
        "climate": sensors.climate(ctx, _DEVICE),
        "water": sensors.water(ctx, _DEVICE),
        "water_settings": sensors.water_settings(ctx, _DEVICE),
        "gps": sensors.gps(ctx, _DEVICE),
        "gps_distance": sensors.gps_distance(ctx, _DEVICE, days=60),
        "energy": sensors.energy(ctx, _DEVICE),
        "weather": sensors.weather(ctx, _DEVICE),
        "system": system.system_status(ctx, _DEVICE),
    }
