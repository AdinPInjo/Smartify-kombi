"""Minimal systemd notification support (no extra dependency).

With ``Type=notify`` and ``WatchdogSec=`` in the unit, systemd restarts the
service when the heartbeat stops, and the unit's ``ExecStopPost`` switches every
relay off (``python -m smartify.failsafe``).
"""

from __future__ import annotations

import os
import socket


def notify(message: str) -> bool:
    """Send a message to systemd. Returns False when not running under systemd."""
    address = os.environ.get("NOTIFY_SOCKET")
    if not address:
        return False
    if address.startswith("@"):
        address = "\0" + address[1:]  # abstract namespace socket
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
        sock.connect(address)
        sock.sendall(message.encode())
    return True
