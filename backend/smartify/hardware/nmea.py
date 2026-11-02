"""Minimal NMEA 0183 parser for GPS receivers.

Only the two sentences needed for position tracking are parsed:

* ``RMC``: position, speed and course, plus a validity flag.
* ``GGA``: fix quality, satellite count and altitude.

Talker prefixes (``GP``, ``GN``, ``GL``...) are ignored. Pure functions only,
so this module is easy to test without a receiver.
"""

from __future__ import annotations

from dataclasses import dataclass

KNOTS_TO_KMH = 1.852


@dataclass(frozen=True)
class RmcSentence:
    valid: bool
    lat: float | None
    lon: float | None
    speed_kmh: float | None
    course: float | None


@dataclass(frozen=True)
class GgaSentence:
    has_fix: bool
    lat: float | None
    lon: float | None
    satellites: int | None
    altitude_m: float | None


def checksum_ok(line: str) -> bool:
    """Validate the ``*hh`` checksum. Lines without a checksum are accepted."""
    if "*" not in line:
        return True
    body, _, given = line.lstrip("$").partition("*")
    calculated = 0
    for char in body:
        calculated ^= ord(char)
    try:
        return calculated == int(given[:2], 16)
    except ValueError:
        return False


def to_decimal(coord: str, hemisphere: str) -> float | None:
    """Convert ``ddmm.mmmm`` / ``dddmm.mmmm`` plus N/S/E/W to decimal degrees."""
    if not coord or "." not in coord or not hemisphere:
        return None
    hemi = hemisphere.upper()
    if hemi in ("N", "S"):
        degree_digits = 2
    elif hemi in ("E", "W"):
        degree_digits = 3
    else:
        return None
    try:
        degrees = float(coord[:degree_digits])
        minutes = float(coord[degree_digits:])
    except ValueError:
        return None
    value = degrees + minutes / 60.0
    return -value if hemi in ("S", "W") else value


def _float(value: str) -> float | None:
    try:
        return float(value) if value else None
    except ValueError:
        return None


def _int(value: str) -> int | None:
    try:
        return int(value) if value else None
    except ValueError:
        return None


def parse(line: str) -> RmcSentence | GgaSentence | None:
    """Parse one NMEA line. Returns ``None`` for unknown or malformed sentences."""
    line = line.strip()
    if not line.startswith("$") or not checksum_ok(line):
        return None
    fields = line.split("*", 1)[0].split(",")
    sentence = fields[0][3:] if len(fields[0]) >= 6 else ""

    if sentence == "RMC" and len(fields) >= 9:
        speed_knots = _float(fields[7])
        return RmcSentence(
            valid=fields[2] == "A",
            lat=to_decimal(fields[3], fields[4]),
            lon=to_decimal(fields[5], fields[6]),
            speed_kmh=None if speed_knots is None else speed_knots * KNOTS_TO_KMH,
            course=_float(fields[8]),
        )

    if sentence == "GGA" and len(fields) >= 10:
        return GgaSentence(
            has_fix=(_int(fields[6]) or 0) > 0,
            lat=to_decimal(fields[2], fields[3]),
            lon=to_decimal(fields[4], fields[5]),
            satellites=_int(fields[7]),
            altitude_m=_float(fields[9]),
        )

    return None
