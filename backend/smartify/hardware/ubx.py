"""u-blox UBX binary messages to tune the receiver for a van.

Sent once each time the GPS port is opened (the settings live in the receiver's
RAM, nothing is written to its flash):

* ``CFG-NAV5``: automotive dynamic model plus *static hold*. Below the threshold
  speed the receiver freezes its position instead of letting it wander, which is
  what makes a parked van "bounce" on the map with a weak signal.
* ``CFG-SBAS``: use SBAS corrections (EGNOS over Europe) for range, differential
  corrections and integrity. Improves accuracy when the satellites are visible.

Works on u-blox 6/7/8 (NEO-6M, the common "u-blox 7" USB dongles, NEO-M8N).
Other receivers ignore the binary bytes. Pure functions, easy to test.
"""

from __future__ import annotations

import struct

SYNC = b"\xb5\x62"

CLS_ACK = 0x05
ID_ACK_ACK = 0x01
ID_ACK_NAK = 0x00

CLS_CFG = 0x06
ID_CFG_NAV5 = 0x24
ID_CFG_SBAS = 0x16

# CFG-NAV5 mask bits: which fields of the message to apply.
_NAV5_MASK_DYN = 0x0001
_NAV5_MASK_STATIC_HOLD = 0x0040

DYN_MODEL_AUTOMOTIVE = 4


def checksum(body: bytes) -> bytes:
    """8-bit Fletcher checksum over class, id, length and payload."""
    a = b = 0
    for byte in body:
        a = (a + byte) & 0xFF
        b = (b + a) & 0xFF
    return bytes((a, b))


def frame(msg_class: int, msg_id: int, payload: bytes = b"") -> bytes:
    body = struct.pack("<BBH", msg_class, msg_id, len(payload)) + payload
    return SYNC + body + checksum(body)


def cfg_nav5(static_hold_cm_s: int = 50, dyn_model: int = DYN_MODEL_AUTOMOTIVE) -> bytes:
    """Automotive model and static hold below ``static_hold_cm_s`` (50 cm/s = 1.8 km/h)."""
    if not 0 <= static_hold_cm_s <= 255:
        raise ValueError("static hold threshold is 0-255 cm/s")
    payload = struct.pack(
        "<HBBiIbBHHHHBBBBHII",
        _NAV5_MASK_DYN | _NAV5_MASK_STATIC_HOLD,
        dyn_model,
        0,  # fixMode (not applied)
        0,  # fixedAlt
        0,  # fixedAltVar
        0,  # minElev
        0,  # drLimit
        0,  # pDop
        0,  # tDop
        0,  # pAcc
        0,  # tAcc
        static_hold_cm_s,
        0,  # dgpsTimeOut
        0,  # cnoThreshNumSVs
        0,  # cnoThresh
        0,
        0,
        0,  # reserved
    )
    return frame(CLS_CFG, ID_CFG_NAV5, payload)


def cfg_sbas() -> bytes:
    """Enable SBAS (EGNOS in Europe) for ranging, corrections and integrity; auto-scan PRNs."""
    mode = 0x01  # enabled, not test mode
    usage = 0x07  # range | diffCorr | integrity
    max_sbas = 3
    payload = struct.pack("<BBBBI", mode, usage, max_sbas, 0, 0)
    return frame(CLS_CFG, ID_CFG_SBAS, payload)


def find_ack(buffer: bytes, msg_class: int, msg_id: int) -> bool | None:
    """True for ACK-ACK, False for ACK-NAK of that message, None if neither is in ``buffer``."""
    for ack_id, result in ((ID_ACK_ACK, True), (ID_ACK_NAK, False)):
        body = struct.pack("<BBHBB", CLS_ACK, ack_id, 2, msg_class, msg_id)
        if SYNC + body + checksum(body) in buffer:
            return result
    return None


# What to send, with a short name for the log.
TUNING = (
    ("static hold + automotive model", CLS_CFG, ID_CFG_NAV5, cfg_nav5()),
    ("SBAS/EGNOS corrections", CLS_CFG, ID_CFG_SBAS, cfg_sbas()),
)
