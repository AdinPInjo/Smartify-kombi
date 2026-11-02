"""Errors the API turns into specific HTTP status codes."""

from __future__ import annotations


class NotFound(LookupError):
    """404: the relay, rule or sensor does not exist."""


class InvalidInput(ValueError):
    """422: the request is well-formed but its values are not acceptable."""


class Conflict(ValueError):
    """409: the change clashes with the current configuration (e.g. pin already used)."""


class DeviceUnavailable(RuntimeError):
    """503: the hardware did not respond, so the change was not made."""
