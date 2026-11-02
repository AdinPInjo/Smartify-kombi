"""SQLite storage for the device.

The Pi keeps all data locally so the van works without internet. Each call to
:func:`connect` returns a new connection; SQLite in WAL mode handles the
background workers and API requests reading/writing at the same time.
"""

from smartify.db.connection import connect, transaction
from smartify.db.migrations import current_version, migrate

__all__ = ["connect", "transaction", "migrate", "current_version"]
