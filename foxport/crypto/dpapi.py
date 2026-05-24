"""Windows DPAPI + AES-GCM decryption for Chromium Login Data.

Chromium (Chrome 80+, Brave, Edge, Vivaldi, Opera) encrypts saved passwords with
AES-256-GCM, where the AES key itself is wrapped by Windows DPAPI in
``Local State`` under ``os_crypt.encrypted_key`` (base64, prefixed with "DPAPI").

Per-entry layout:
    v10|v11    (3 bytes, version tag)
    nonce      (12 bytes)
    ciphertext (variable)
    tag        (16 bytes)
"""

from __future__ import annotations

import base64
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class DecryptionError(RuntimeError):
    """Raised when a password blob cannot be decrypted."""


@dataclass(frozen=True)
class ChromiumKey:
    """Decrypted AES-256 master key extracted from ``Local State``."""

    key: bytes

    def __post_init__(self) -> None:
        if len(self.key) != 32:
            raise DecryptionError(f"expected 32-byte AES key, got {len(self.key)}")


def _dpapi_unprotect(blob: bytes) -> bytes:
    """Run Windows DPAPI ``CryptUnprotectData`` against ``blob``.

    Only works on the same Windows user account that originally encrypted the
    data. On non-Windows, this is unreachable and raises.
    """
    if sys.platform != "win32":
        raise DecryptionError("DPAPI is only available on Windows")
    import win32crypt  # type: ignore[import-not-found]

    try:
        _desc, plaintext = win32crypt.CryptUnprotectData(blob, None, None, None, 0)
    except Exception as exc:  # pywin32 raises a generic pywintypes.error
        raise DecryptionError(f"DPAPI unprotect failed: {exc}") from exc
    return bytes(plaintext)


def load_master_key(local_state_path: Path) -> ChromiumKey:
    """Extract and decrypt the AES master key from a Chromium ``Local State`` file."""
    raw = local_state_path.read_text(encoding="utf-8", errors="ignore")
    data = json.loads(raw)
    encrypted_b64 = data.get("os_crypt", {}).get("encrypted_key")
    if not encrypted_b64:
        raise DecryptionError(f"no os_crypt.encrypted_key in {local_state_path}")
    wrapped = base64.b64decode(encrypted_b64)
    if not wrapped.startswith(b"DPAPI"):
        raise DecryptionError("encrypted_key missing DPAPI prefix")
    key = _dpapi_unprotect(wrapped[5:])
    return ChromiumKey(key=key)


def decrypt_value(blob: bytes, master: ChromiumKey) -> str:
    """Decrypt a single Chromium-encrypted value (password, cookie, etc.).

    Returns the decoded UTF-8 string. Raises :class:`DecryptionError` on failure.
    Handles both modern (v10/v11 AES-GCM) and legacy (raw DPAPI) blobs.
    """
    if not blob:
        return ""
    prefix = blob[:3]
    if prefix in (b"v10", b"v11"):
        nonce = blob[3:15]
        ct_and_tag = blob[15:]
        aes = AESGCM(master.key)
        try:
            plaintext = aes.decrypt(nonce, ct_and_tag, None)
        except Exception as exc:
            raise DecryptionError(f"AES-GCM decrypt failed: {exc}") from exc
        return plaintext.decode("utf-8", errors="replace")
    # Pre-Chromium 80: raw DPAPI-encrypted UTF-16LE string
    try:
        plaintext = _dpapi_unprotect(blob)
    except DecryptionError:
        raise
    try:
        return plaintext.decode("utf-16-le", errors="replace").rstrip("\x00")
    except UnicodeDecodeError:
        return plaintext.decode("utf-8", errors="replace")
