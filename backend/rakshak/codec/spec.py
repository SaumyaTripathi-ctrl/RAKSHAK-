"""Constants of record format v1. Mirrors firmware/common/include/rk_spec.h - keep in sync.

See firmware/common/spec/RECORD_SPEC.md for the normative description.
"""

from __future__ import annotations

import struct
from enum import IntEnum, IntFlag

VERSION = 1

HASH_LEN = 32
KEY_LEN = 32
NONCE_LEN = 12
GCM_TAG_LEN = 16
DEVICE_ID_LEN = 16
SHIPMENT_ID_LEN = 16
GENESIS_HASH = bytes(HASH_LEN)

HKDF_INFO_PREFIX = b"rakshak-v1|"


class RecordType(IntEnum):
    TAG_SAMPLE = 1
    HUB_SAMPLE = 2
    EVENT = 3


class EventCode(IntEnum):
    """Event codes carried in EVENT records (``event_code`` field)."""

    TIME_SYNC = 1  # ts = epoch at sync, arg0|arg1<<16 = device monotonic seconds at sync
    BOOT = 2  # device clock origin restarted (power loss / reset)
    LID_OPEN = 3
    SHOCK = 4  # arg0 = shock_g_x100
    LOW_BATTERY = 5
    PAIRED = 6
    KEY_ROTATED = 7  # arg0 = new key_epoch


class TagFlags(IntFlag):
    LID_OPEN = 1 << 0
    TS_VALID = 1 << 1


class HubFlags(IntFlag):
    LID_OPEN = 1 << 0
    TS_VALID = 1 << 1
    GPS_VALID = 1 << 2
    FAN_ON = 1 << 3


# Common 42-byte header shared by all bodies.
COMMON_FMT = "<BB16s16sII"  # version, type, device_id, shipment_id, seq, ts
COMMON_LEN = struct.calcsize(COMMON_FMT)

TAG_BODY_FMT = COMMON_FMT + "hHHBB"  # temp_x100, rh_x100, ethylene_idx_x10, flags, batt_pct
HUB_BODY_FMT = (
    COMMON_FMT + "hHHiiBBBB"
)  # temp, rh, shock_g_x100, lat_e6, lon_e6, flags, flap, batt, alert
EVENT_BODY_FMT = COMMON_FMT + "HHHBB"  # event_code, arg0, arg1, flags, batt_pct

BODY_LEN = {
    RecordType.TAG_SAMPLE: struct.calcsize(TAG_BODY_FMT),
    RecordType.HUB_SAMPLE: struct.calcsize(HUB_BODY_FMT),
    RecordType.EVENT: struct.calcsize(EVENT_BODY_FMT),
}

# Frame header (also the AAD): version, type, device_id, key_epoch, seq.
HEADER_FMT = "<BB16sHI"
HEADER_LEN = struct.calcsize(HEADER_FMT)

# Plaintext inside a frame = body || prev_hash || hash.
PLAINTEXT_LEN = {t: n + 2 * HASH_LEN for t, n in BODY_LEN.items()}
FRAME_LEN = {t: HEADER_LEN + n + GCM_TAG_LEN for t, n in PLAINTEXT_LEN.items()}

# Hard size assertions: the C side has matching _Static_asserts.
assert COMMON_LEN == 42
assert BODY_LEN[RecordType.TAG_SAMPLE] == 50
assert BODY_LEN[RecordType.EVENT] == 50
assert BODY_LEN[RecordType.HUB_SAMPLE] == 60
assert HEADER_LEN == 24
assert PLAINTEXT_LEN[RecordType.TAG_SAMPLE] == 114
assert PLAINTEXT_LEN[RecordType.HUB_SAMPLE] == 124
assert FRAME_LEN[RecordType.TAG_SAMPLE] == 154
assert FRAME_LEN[RecordType.EVENT] == 154
assert FRAME_LEN[RecordType.HUB_SAMPLE] == 164
MAX_FRAME_LEN = max(FRAME_LEN.values())
