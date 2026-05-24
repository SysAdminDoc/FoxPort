"""Mozilla ``mfbt::HashString`` port + Firefox ``places.sqlite.url_hash``.

Firefox's Places module hashes URLs with a custom 64-bit function:
the high 16 bits come from ``HashString(scheme + "://") & 0xFFFF``,
the low 32 bits from ``HashString(url)`` capped at 1500 characters.

The hash itself is **not** MD5, not SipHash, not CityHash. It's the
``AddU32ToHash`` mix from ``mfbt/HashFunctions.h`` — a multiply-rotate-xor
mix seeded with the 32-bit golden ratio constant. Re-implemented here
exactly so FoxPort's emitted ``moz_places.url_hash`` values match what
Firefox computes on first visit, which keeps AwesomeBar dedup and
frecency lookups working.

Reference: ``mozilla-central/mfbt/HashFunctions.h``,
``toolkit/components/places/Helpers.cpp``.
"""

from __future__ import annotations

from urllib.parse import urlsplit

_GOLDEN_RATIO_U32 = 0x9E3779B9
_U32_MASK = 0xFFFFFFFF

# Firefox caps the URL portion of url_hash at this many bytes. Beyond this,
# AddU32ToHash silently skips the tail — must match.
_URL_HASH_MAX_LEN = 1500


def _rotate_left_5(value: int) -> int:
    """mfbt ``RotateLeft5(x)`` — 32-bit left rotation by 5."""
    return ((value << 5) | (value >> 27)) & _U32_MASK


def _add_u32_to_hash(hash_val: int, val: int) -> int:
    """mfbt ``AddU32ToHash(hash, val)`` — multiply-rotate-xor mix."""
    return (_GOLDEN_RATIO_U32 * (_rotate_left_5(hash_val) ^ (val & _U32_MASK))) & _U32_MASK


def hash_string(s: str) -> int:
    """Mozilla mfbt ``HashString`` — non-cryptographic 32-bit mix.

    Iterates over the UTF-8 bytes of ``s`` (mfbt operates on ``Char`` units;
    for ASCII URLs this is equivalent). Empty string hashes to 0.
    """
    hash_val = 0
    for ch in s.encode("utf-8"):
        hash_val = _add_u32_to_hash(hash_val, ch)
    return hash_val


def places_url_hash(url: str) -> int:
    """Firefox-compatible 64-bit ``moz_places.url_hash`` for ``url``.

    Layout matches ``toolkit/components/places/Helpers.cpp::HashURL``:

    * High 16 bits: ``HashString(scheme + "://") & 0xFFFF`` (0 when no scheme).
    * Low 32 bits:  ``HashString(url_truncated_to_1500_chars)``.
    """
    if not url:
        return 0
    capped = url[:_URL_HASH_MAX_LEN]
    parts = urlsplit(capped)
    if parts.scheme:
        prefix_hash = hash_string(f"{parts.scheme}://") & 0xFFFF
    else:
        prefix_hash = 0
    return (prefix_hash << 32) | hash_string(capped)
